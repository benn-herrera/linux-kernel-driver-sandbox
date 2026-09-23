/* SPDX-License-Identifier: GPL-2.0 */
#pragma once

#include <linux/completion.h>
#include <linux/dma-mapping.h>
#include <linux/errno.h>
#include <linux/fs.h>
#include <linux/interrupt.h>
#include <linux/miscdevice.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/pci.h>

#include "mxm_ioctl.h"

//
// enums and macro constants
//
#define MXM_NAME "matx_mock"
#define MXM_VENDOR_ID 0x1234
#define MXM_DEVICE_ID 0x11e8
#define MXM_DMA_MASK DMA_BIT_MASK(32)

enum mxm_register {
	MXM_REG_ID = 0x00,
	MXM_REG_LIVENESS = 0x04,
	MXM_REG_COMPUTE = 0x08,
	MXM_REG_STATUS = 0x20,
	MXM_REG_INTERRUPT_STATUS = 0x24,
	MXM_REG_INTERRUPT_RAISE = 0x60,
	MXM_REG_INTERRUPT_ACK = 0x64,
	MXM_REG_DMA_SOURCE = 0x80,
	MXM_REG_DMA_DEST = 0x88,
	MXM_REG_DMA_COUNT = 0x90,
	MXM_REG_DMA_COMMAND = 0x98,
};

enum mxm_compute_status_bit {
	MXM_COMPUTE_STATUS_BIT_WORKING = 0x01,
	MXM_COMPUTE_STATUS_BIT_RAISE_ON_COMPLETION = 0x80,
};

enum mxm_dma_command_bit {
	MXM_DMA_COMMAND_BIT_START = 0x01,
	MXM_DMA_COMMAND_BIT_DIRECTION = 0x02,
	MXM_DMA_COMMAND_BIT_RAISE = 0x04,
};

enum mxm_irq_value {
	MXM_IRQ_COMPUTE = 0x01,
	MXM_IRQ_DMA = 0x100,
};

enum mxm_dma_direction {
	MXM_DMA_DIRECTION_RAM_TO_DEVICE = 0,
	MXM_DMA_DIRECTION_DEVICE_TO_RAM = 1,
};

//
// structures
//
struct mxm_dev {
	struct pci_dev *pdev;
	void __iomem *regs;
	struct miscdevice miscdev;
	struct mutex compute_lock;
	struct completion compute_done;
	struct mutex dma_lock;
	struct completion dma_done;
	int irq;
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

// file descriptor operations
extern int mxm_open(struct inode *inode, struct file *file);
extern int mxm_release(struct inode *inode, struct file *file);
extern long mxm_ioctl(struct file *file, unsigned int cmd, unsigned long arg);

// interrupt handler
extern irqreturn_t mxm_irq(int irq, void *dev_id);

// DMA operations
extern int mxm_dma_host_to_device(struct pci_dev *pdev, const void *src,
				  u64 dest);
extern int mxm_dma_device_to_host(struct pci_dev *pdev, u64 src, void *dst);
