// SPDX-License-Identifier: GPL-2.0
/*
 * probe_remove: device setup/shutdown cycle
 */
#include "common.h"
#include <linux/slab.h>

int tcd_probe(struct pci_dev *pdev, const struct pci_device_id *id)
{
	static const struct file_operations tcd_fops = { .owner = THIS_MODULE,
							 .open = tcd_open,
							 .release = tcd_release,
							 .unlocked_ioctl =
								 tcd_ioctl };

	struct tcd_dev *tcd = NULL;
	int error = 0;

	// lifetime managed by device. tcd_remove does not need to deallocate
	tcd = devm_kzalloc(&pdev->dev, sizeof(*tcd), GFP_KERNEL);
	if (!tcd)
		return dev_err_probe(&pdev->dev, -ENOMEM, "out of memory.\n");

	// basic setup - enable, read the BARs
	error = pcim_enable_device(pdev);
	if (error)
		return dev_err_probe(&pdev->dev, error, "enable failed.\n");

	tcd->regs = pcim_iomap_region(pdev, 0, TCD_NAME);
	if (IS_ERR(tcd->regs))
		return dev_err_probe(&pdev->dev, PTR_ERR(tcd->regs),
				     "iomap region failed.\n");

	tcd->pdev = pdev;

	{
		u32 tcdid = ioread32(tcd->regs + TCD_REG_ID);

		dev_info(&pdev->dev, "id %#010x\n", tcdid);
	}

	// dma setup
	pci_set_master(pdev);
	error = dma_set_mask_and_coherent(&pdev->dev, TCD_DMA_MASK);
	if (error)
		return dev_err_probe(&pdev->dev, error,
				     "dma set mask failed.\n");

	// device-scoped interrupt handler completion
	init_completion(&tcd->compute_done);
	init_completion(&tcd->dma_done);
	mutex_init(&tcd->compute_lock);
	mutex_init(&tcd->dma_lock);
	error = pci_alloc_irq_vectors(pdev, 1, 1, PCI_IRQ_ALL_TYPES);
	if (error < 0)
		return dev_err_probe(&pdev->dev, error,
				     "pci irq vector allocation failed.\n");

	tcd->irq = pci_irq_vector(pdev, 0);
	error = request_irq(tcd->irq, tcd_irq, IRQF_SHARED, KBUILD_MODNAME,
			    tcd);
	if (error) {
		pci_free_irq_vectors(pdev);
		return dev_err_probe(&pdev->dev, error,
				     "request irq failed.\n");
	}

	// misc device file descriptor operations registration
	// requires matching unregister in remove()
	tcd->miscdev.name = KBUILD_MODNAME;
	tcd->miscdev.minor = MISC_DYNAMIC_MINOR;
	tcd->miscdev.fops = &tcd_fops;
	error = misc_register(&tcd->miscdev);
	if (error) {
		free_irq(tcd->irq, tcd);
		pci_free_irq_vectors(pdev);
		return dev_err_probe(&pdev->dev, error,
				     "misc registration failed.\n");
	}

	// assign driver data pointer for access by other driver functions
	pci_set_drvdata(pdev, tcd);

	return 0;
}

void tcd_remove(struct pci_dev *pdev)
{
	struct tcd_dev *tcd = pci_get_drvdata(pdev);

	if (tcd) {
		misc_deregister(&tcd->miscdev);
		free_irq(tcd->irq, tcd);
		pci_free_irq_vectors(pdev);
	}
}
