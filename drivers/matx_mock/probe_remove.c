// SPDX-License-Identifier: GPL-2.0
#include "common.h"

int mxm_probe(struct pci_dev *pdev, const struct pci_device_id *id)
{
	(void)pdev;
	(void)id;
	// dma_set_mask_and_coherent(&dev->dev, MXM_DMA_MASK, 0);
	return 0;
}

void mxm_remove(struct pci_dev *pdev)
{
	(void)pdev;
}
