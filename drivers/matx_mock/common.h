/* SPDX-License-Identifier: GPL-2.0 */
#pragma once

#include <linux/pci.h>

// lifecycle
extern int mxm_init(void);
extern void mxm_exit(void);

extern int mxm_probe(struct pci_dev *pdev, const struct pci_device_id *id);
extern void mxm_remove(struct pci_dev *pdev);

#define MXM_VENDOR_ID 0x1234
#define MXM_DEVICE_ID 0x11e8
#define MXM_DMA_MASK DMA_BIT_MASK(32)
