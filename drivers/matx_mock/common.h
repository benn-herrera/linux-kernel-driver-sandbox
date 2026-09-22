/* SPDX-License-Identifier: GPL-2.0 */
#pragma once

#include <linux/dma-mapping.h>
#include <linux/module.h>
#include <linux/pci.h>

//
// macros and constants
//
#define MXM_NAME "matx_mock"
#define MXM_VENDOR_ID 0x1234
#define MXM_DEVICE_ID 0x11e8
#define MXM_DMA_MASK DMA_BIT_MASK(32)

enum mxm_register {
	MXM_REG_ID = 0x00,
	MXM_REG_LIVENESS = 0x04,
	MXM_REG_FACTORIAL = 0x08,
	MXM_REG_STATUS = 0x20,
	MXM_REG_INTERRUPT_STATUS = 0x24,
	MXM_REG_INTERRUPT_RAISE = 0x60,
	MXM_REG_INTERRUPT_ACK = 0x64,
	MXM_REG_DMA_SOURCE = 0x80,
	MXM_REG_DMA_DEST = 0x88,
	MXM_REG_DMA_COUNT = 0x90,
	MXM_REG_DMA_COMMAND = 0x98
};

//
// structures
//
struct mxm_dev {
	struct pci_dev *pdev;
	void __iomem *regs;
};

//
// prototypes
//

// lifecycle
extern int mxm_init(void);
extern void mxm_exit(void);

// activation cycle
extern int mxm_probe(struct pci_dev *pdev, const struct pci_device_id *id);
extern void mxm_remove(struct pci_dev *pdev);
