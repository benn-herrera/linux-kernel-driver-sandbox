// SPDX-License-Identifier: GPL-2.0
/*
 * irq: live device interrupt handler
 */
#include "common.h"

irqreturn_t mxm_irq(int irq, void *dev_id)
{
	struct mxm_dev *mxm = dev_id;
	u32 status = ioread32(mxm->regs + MXM_REG_INTERRUPT_STATUS);

	if (status == 0)
		return IRQ_NONE;

	iowrite32(status, mxm->regs + MXM_REG_INTERRUPT_ACK);

	if (status & MXM_IRQ_COMPUTE)
		complete(&mxm->compute_done);

	if (status & MXM_IRQ_DMA)
		complete(&mxm->dma_done);

	return IRQ_HANDLED;
}
