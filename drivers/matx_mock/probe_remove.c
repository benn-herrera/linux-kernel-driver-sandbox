// SPDX-License-Identifier: GPL-2.0
/*
 * probe_remove: device setup/shutdown cycle
 */
#include "common.h"
#include <linux/slab.h>

int mxm_probe(struct pci_dev *pdev, const struct pci_device_id *id)
{
	static const struct file_operations mxm_fops = { .owner = THIS_MODULE,
							 .open = mxm_open,
							 .release = mxm_release,
							 .unlocked_ioctl =
								 mxm_ioctl };

	struct mxm_dev *mxm = NULL;
	int error = 0;

	// lifetime managed by device. mxm_remove does not need to deallocate
	mxm = devm_kzalloc(&pdev->dev, sizeof(*mxm), GFP_KERNEL);
	if (!mxm)
		return dev_err_probe(&pdev->dev, -ENOMEM, "out of memory.\n");

	// basic setup - enable, read the BARs
	error = pcim_enable_device(pdev);
	if (error)
		return dev_err_probe(&pdev->dev, error, "enable failed.\n");

	mxm->regs = pcim_iomap_region(pdev, 0, MXM_NAME);
	if (IS_ERR(mxm->regs))
		return dev_err_probe(&pdev->dev, PTR_ERR(mxm->regs),
				     "iomap region failed.\n");

	mxm->pdev = pdev;

	{
		u32 mxmid = ioread32(mxm->regs + MXM_REG_ID);

		dev_info(&pdev->dev, "id %#010x\n", mxmid);
	}

	// dma setup
	pci_set_master(pdev);
	error = dma_set_mask_and_coherent(&pdev->dev, MXM_DMA_MASK);
	if (error)
		return dev_err_probe(&pdev->dev, error,
				     "dma set mask failed.\n");

	// device-scoped interrupt handler completion
	init_completion(&mxm->compute_done);
	init_completion(&mxm->dma_done);
	mutex_init(&mxm->compute_lock);
	mutex_init(&mxm->dma_lock);
	error = pci_alloc_irq_vectors(pdev, 1, 1, PCI_IRQ_ALL_TYPES);
	if (error < 0)
		return dev_err_probe(&pdev->dev, error,
				     "pci irq vector allocation failed.\n");

	mxm->irq = pci_irq_vector(pdev, 0);
	error = request_irq(mxm->irq, mxm_irq, IRQF_SHARED, KBUILD_MODNAME,
			    mxm);
	if (error) {
		pci_free_irq_vectors(pdev);
		return dev_err_probe(&pdev->dev, error,
				     "request irq failed.\n");
	}

	// misc device file descriptor operations registration
	// requires matching unregister in remove()
	mxm->miscdev.name = KBUILD_MODNAME;
	mxm->miscdev.minor = MISC_DYNAMIC_MINOR;
	mxm->miscdev.fops = &mxm_fops;
	error = misc_register(&mxm->miscdev);
	if (error) {
		free_irq(mxm->irq, mxm);
		pci_free_irq_vectors(pdev);
		return dev_err_probe(&pdev->dev, error,
				     "misc registration failed.\n");
	}

	// assign driver data pointer for access by other driver functions
	pci_set_drvdata(pdev, mxm);

	return 0;
}

void mxm_remove(struct pci_dev *pdev)
{
	struct mxm_dev *mxm = pci_get_drvdata(pdev);

	if (mxm) {
		misc_deregister(&mxm->miscdev);
		free_irq(mxm->irq, mxm);
		pci_free_irq_vectors(pdev);
	}
}
