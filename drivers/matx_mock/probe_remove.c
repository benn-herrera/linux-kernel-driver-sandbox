// SPDX-License-Identifier: GPL-2.0
/*
 * probe_remove: device setup/shutdown cycle
 */
#include "common.h"
#include <linux/slab.h>

int mxm_probe(struct pci_dev *pdev, const struct pci_device_id *id)
{
	struct mxm_dev *pmxm = NULL;
	int error = 0;
	u32 mxmid = 0;

	// lifetime managed by device. mxm_remove does not need to deallocate
	pmxm = devm_kzalloc(&pdev->dev, sizeof(*pmxm), GFP_KERNEL);
	if (!pmxm)
		return dev_err_probe(&pdev->dev, -ENOMEM, "out of memory.\n");

	error = pcim_enable_device(pdev);
	if (error)
		return dev_err_probe(&pdev->dev, error, "enable failed.\n");

	pmxm->regs = pcim_iomap_region(pdev, 0, MXM_NAME);
	if (IS_ERR(pmxm->regs))
		return dev_err_probe(&pdev->dev, PTR_ERR(pmxm->regs),
				     "iomap region failed.\n");

	mxmid = ioread32(pmxm->regs + MXM_REG_ID);
	dev_info(&pdev->dev, "id %#010x\n", mxmid);

	// dma setup
	pci_set_master(pdev);
	error = dma_set_mask_and_coherent(&pdev->dev, MXM_DMA_MASK);
	if (error)
		return dev_err_probe(&pdev->dev, error,
				     "dma set mask failed.\n");

	// assign driver data pointer for access by other driver functions
	pci_set_drvdata(pdev, pmxm);

	return 0;
}

void mxm_remove(struct pci_dev *pdev)
{
	// nothing to do yet. devm system manages mxm device struct lifetime.
}
