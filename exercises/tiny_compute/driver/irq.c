// SPDX-License-Identifier: GPL-2.0
/*
 * irq: live device interrupt handler
 */
#include "common.h"

irqreturn_t tcd_irq(int irq, void *dev_id)
{
	struct tcd_dev *tcd = dev_id;
	u32 status = ioread32(tcd->regs + TCD_REG_INTERRUPT_STATUS);

	if (status == 0)
		return IRQ_NONE;

	iowrite32(status, tcd->regs + TCD_REG_INTERRUPT_ACK);

	if (status & TCD_IRQ_COMPUTE)
		complete(&tcd->compute_done);

	if (status & TCD_IRQ_DMA)
		complete(&tcd->dma_done);

	return IRQ_HANDLED;
}
