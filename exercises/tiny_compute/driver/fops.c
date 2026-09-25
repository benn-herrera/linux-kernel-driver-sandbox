// SPDX-License-Identifier: GPL-2.0
/*
 * fops: live device file descriptor operations
 */
#include "common.h"
#include "tcd_ioctl.h"
#include <linux/cleanup.h>
#include <linux/uaccess.h>

struct tcd_file {
	struct tcd_dev *tcd;
	// other stuff will go here eventually
};

static_assert(TCD_DEVICE_CAP_COMPUTE == TCD_CAP_COMPUTE);
static_assert(TCD_DEVICE_CAP_DMA_READ == TCD_CAP_DMA_READ);
static_assert(TCD_DEVICE_CAP_DMA_WRITE == TCD_CAP_DMA_WRITE);
// would be nice to be able to pin this like the device caps.
//static_assert(TCD_DEVICE_NAME_BASE == KBUILD_MODNAME);

int tcd_open(struct inode *inode, struct file *file)
{
	struct tcd_dev *pdev =
		container_of(file->private_data, struct tcd_dev, miscdev);
	struct tcd_file *mfile = NULL;

	mfile = kzalloc_obj(struct tcd_file, GFP_KERNEL);
	if (!mfile)
		return -ENOMEM;

	mfile->tcd = pdev;
	file->private_data = mfile;

	return 0;
}

int tcd_release(struct inode *inode, struct file *file)
{
	struct tcd_file *mfile = file->private_data;

	if (!mfile)
		return -EFAULT;

	kvfree(file->private_data);
	mfile = file->private_data = NULL;

	return 0;
}

long tcd_ioctl(struct file *file, unsigned int cmd, unsigned long arg)
{
	struct tcd_file *mfile = file->private_data;

	if (!mfile)
		return -EFAULT;

	switch (cmd) {
	case TCD_IOC_INFO: {
		struct tcd_info info = {};

		info.abi_version = TCD_ABI_VERSION;
		info.device_id = ioread32(mfile->tcd->regs + TCD_REG_ID);
		info.dma_buf_size = TCD_DMA_BUF_SIZE;
		info.dma_alignment = TCD_DMA_ALIGNMENT;
		info.flags = mfile->tcd->cap_flags;

		if (copy_to_user((void __user *)arg, &info, sizeof(info)))
			return -EFAULT;

		return 0;
	}
	case TCD_IOC_LIVENESS: {
		u32 val = 0;

		if (get_user(val, (u32 __user *)arg))
			return -EFAULT;

		iowrite32(val, mfile->tcd->regs + TCD_REG_LIVENESS);
		val = ioread32(mfile->tcd->regs + TCD_REG_LIVENESS);

		if (put_user(val, (u32 __user *)arg))
			return -EFAULT;

		return 0;
	}
	case TCD_IOC_COMPUTE: {
		u32 val = 0;
		int result = 0;

		if (!(mfile->tcd->cap_flags & TCD_CAP_COMPUTE))
		  return -EFAULT;

		if (get_user(val, (u32 __user *)arg))
			return -EFAULT;

		scoped_cond_guard(mutex_intr, return -ERESTARTSYS,
				  &mfile->tcd->compute_lock)
		{
			reinit_completion(&mfile->tcd->compute_done);
			iowrite32(TCD_COMPUTE_STATUS_BIT_RAISE_ON_COMPLETION,
				  mfile->tcd->regs + TCD_REG_STATUS);
			iowrite32(val, mfile->tcd->regs + TCD_REG_COMPUTE);
			result = wait_for_completion_interruptible_timeout(
				&mfile->tcd->compute_done, HZ);
			if (result <= 0) {
				result = (result == 0) ? -ETIMEDOUT :
							 -ERESTARTSYS;
				if (result == -ETIMEDOUT)
					dev_err_ratelimited(
						&mfile->tcd->pdev->dev,
						"compute timed out. status: 0x%08x\n",
						ioread32(mfile->tcd->regs +
							 TCD_REG_STATUS));
				return result;
			}
			val = ioread32(mfile->tcd->regs + TCD_REG_COMPUTE);
			result = 0;
		}

		if (put_user(val, (u32 __user *)arg))
			return -EFAULT;

		return 0;
	}
	case TCD_IOC_DMA_FROM_DEVICE: {
		struct tcd_dma_req dma_req = {};

		if (!(mfile->tcd->cap_flags & TCD_CAP_DMA_READ))
		  return -EFAULT;

		if (copy_from_user(&dma_req, (const void *)arg,
				   sizeof(dma_req)))
			return -EFAULT;
		return tcd_dma_from_device(mfile->tcd, dma_req.dev_offset,
					   u64_to_user_ptr(dma_req.ubuf),
					   dma_req.count);
	}
	case TCD_IOC_DMA_TO_DEVICE: {
		struct tcd_dma_req dma_req = {};

		if (!(mfile->tcd->cap_flags & TCD_CAP_DMA_WRITE))
		  return -EFAULT;

		if (copy_from_user(&dma_req, (const void *)arg,
				   sizeof(dma_req)))
			return -EFAULT;
		return tcd_dma_to_device(mfile->tcd,
					 u64_to_user_ptr(dma_req.ubuf),
					 dma_req.dev_offset, dma_req.count);
	}
	default:
		break;
	}
	return -ENOTTY;
}
