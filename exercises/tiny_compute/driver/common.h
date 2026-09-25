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

#include "tcd_ioctl.h"

//
// enums and macro constants
//
#define TCD_NAME "tiny_compute"
#define TCD_VENDOR_ID 0x1234
#define TCD_DEVICE_ID 0x11e8
#define TCD_DMA_MASK DMA_BIT_MASK(32)

#define TCD_DMA_BUF_SIZE 4096ull
#define TCD_DMA_ALIGNMENT 16
#define TCD_DMA_DEVICE_BUF 0x40000ull
#define TCD_DMA_DIRECTION_BIT_IDX 1

enum tcd_register {
	TCD_REG_ID = 0x00,
	TCD_REG_LIVENESS = 0x04,
	TCD_REG_COMPUTE = 0x08,
	TCD_REG_STATUS = 0x20,
	TCD_REG_INTERRUPT_STATUS = 0x24,
	TCD_REG_INTERRUPT_RAISE = 0x60,
	TCD_REG_INTERRUPT_ACK = 0x64,
	TCD_REG_DMA_SOURCE = 0x80,
	TCD_REG_DMA_DEST = 0x88,
	TCD_REG_DMA_COUNT = 0x90,
	TCD_REG_DMA_COMMAND = 0x98,
};

enum tcd_compute_status_bit {
	TCD_COMPUTE_STATUS_BIT_WORKING = (1u << 0),
	TCD_COMPUTE_STATUS_BIT_RAISE_ON_COMPLETION = (1u << 7),
};

enum tcd_dma_command_bit {
	TCD_DMA_COMMAND_BIT_START = (1u << 0),
	TCD_DMA_COMMAND_BIT_DIRECTION = (1u << 1),
	TCD_DMA_COMMAND_BIT_RAISE = (1u << 2),
};

enum tcd_irq_value {
	TCD_IRQ_COMPUTE = 0x01,
	TCD_IRQ_DMA = 0x100,
};

enum tcd_dma_direction_bit {
	TCD_DMA_TO_DEVICE = (0u << TCD_DMA_DIRECTION_BIT_IDX),
	TCD_DMA_FROM_DEVICE = (1u << TCD_DMA_DIRECTION_BIT_IDX),
};

enum tcd_cap_bit {
	TCD_CAP_COMPUTE = (1u << 0),
	TCD_CAP_DMA_READ = (1u << 1),
	TCD_CAP_DMA_WRITE = (1u << 2)
};

//
// structures
//

struct tcd_dma_buf {
	void *cpu;
	dma_addr_t dma;
	size_t size;
};

struct tcd_dev {
	struct pci_dev *pdev;
	void __iomem *regs;
	struct miscdevice miscdev;
	struct mutex compute_lock;
	struct completion compute_done;
	struct mutex dma_lock;
	struct completion dma_done;
	struct tcd_dma_buf dma_from_device;
	struct tcd_dma_buf dma_to_device;
	u32 cap_flags;
	int id;
	int irq;
};

//
// prototypes
//

// lifecycle
extern int tcd_init(void);
extern void tcd_exit(void);

// activation cycle
extern int tcd_probe(struct pci_dev *pdev, const struct pci_device_id *id);
extern void tcd_remove(struct pci_dev *pdev);

// file descriptor operations
extern int tcd_open(struct inode *inode, struct file *file);
extern int tcd_release(struct inode *inode, struct file *file);
extern long tcd_ioctl(struct file *file, unsigned int cmd, unsigned long arg);

// interrupt handler
extern irqreturn_t tcd_irq(int irq, void *dev_id);

// DMA operations
extern int tcd_dma_to_device(struct tcd_dev *tcd, const void __user *src,
			     u64 dst, u64 count);
extern int tcd_dma_from_device(struct tcd_dev *tcd, u64 src, void __user *dst,
			       u64 count);
