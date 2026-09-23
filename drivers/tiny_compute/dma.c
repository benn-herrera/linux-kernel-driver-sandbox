// SPDX-License-Identifier: GPL-2.0
/*
 * dma: live device DMA operations
 */
#include "common.h"

int tcd_dma_host_to_device(struct pci_dev *pdev, const void *src, u64 dest)
{
	return -1;
}

int tcd_dma_device_to_host(struct pci_dev *pdev, u64 src, void *dst)
{
	return -1;
}
