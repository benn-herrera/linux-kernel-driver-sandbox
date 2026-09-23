// SPDX-License-Identifier: GPL-2.0
/*
 * dma: live device DMA operations
 */
#include "common.h"
#include <linux/cleanup.h>
#include <linux/io-64-nonatomic-lo-hi.h>
#include <linux/uaccess.h>

static int tcd_dma_xfer(struct tcd_dev *tcd, u64 src, u64 dst, u64 count,
			enum dma_data_direction dir)
{
	u64 cmd_src = ~0ull, cmd_dst = ~0ull;
	int result = 0, cmd = 0;

	if (!count || (count % TCD_DMA_ALIGNMENT) || count > TCD_DMA_BUF_SIZE)
		return -EINVAL;

	switch (dir) {
	case DMA_FROM_DEVICE:
		if (src % TCD_DMA_ALIGNMENT)
			return -EINVAL;
		if (src + count > TCD_DMA_BUF_SIZE)
			return -EINVAL;

		cmd = TCD_DMA_FROM_DEVICE;
		cmd_src = TCD_DMA_DEVICE_BUF + src;
		cmd_dst = tcd->dma_from_device.dma;
		break;

	case DMA_TO_DEVICE:
		if (dst % TCD_DMA_ALIGNMENT)
			return -EINVAL;
		if (dst + count > TCD_DMA_BUF_SIZE)
			return -EINVAL;

		cmd = TCD_DMA_TO_DEVICE;
		cmd_src = tcd->dma_to_device.dma;
		cmd_dst = TCD_DMA_DEVICE_BUF + dst;
		break;
	default:
		return -EINVAL;
	}

	scoped_cond_guard(mutex_intr, return -ERESTARTSYS, &tcd->dma_lock)
	{
		reinit_completion(&tcd->dma_done);

		if (dir == DMA_TO_DEVICE) {
			// stage source data from userspace
			result = copy_from_user(tcd->dma_to_device.cpu,
						(const void __user *)src,
						count);
			if (result)
				return -EFAULT;
		}

		iowrite64(cmd_src, tcd->regs + TCD_REG_DMA_SOURCE);
		iowrite64(cmd_dst, tcd->regs + TCD_REG_DMA_DEST);
		iowrite64(count, tcd->regs + TCD_REG_DMA_COUNT);
		iowrite64(cmd | TCD_DMA_COMMAND_BIT_START |
				  TCD_DMA_COMMAND_BIT_RAISE,
			  tcd->regs + TCD_REG_DMA_COMMAND);

		result = wait_for_completion_interruptible_timeout(
			&tcd->dma_done, HZ);

		if (result > 0) {
			if (dir == DMA_FROM_DEVICE) {
				// relay transferred data to userspace
				result = copy_to_user(
					(void __user *)dst,
					(const void *)tcd->dma_from_device.cpu,
					count);
				if (result)
					return -EFAULT;
			} else
				result = 0;
		} else
			result = (result == 0) ? -ETIMEDOUT : -ERESTARTSYS;
	}

	return result;
}

int tcd_dma_to_device(struct tcd_dev *tcd, const void __user *src, u64 dst,
		      u64 count)
{
	return tcd_dma_xfer(tcd, (u64)src, dst, count, DMA_TO_DEVICE);
}

int tcd_dma_from_device(struct tcd_dev *tcd, u64 src, void __user *dst,
			u64 count)
{
	return tcd_dma_xfer(tcd, src, (u64)dst, count, DMA_FROM_DEVICE);
}
