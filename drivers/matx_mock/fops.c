// SPDX-License-Identifier: GPL-2.0
/*
 * fops: live device file descriptor operations
 */
#include "common.h"
#include <linux/uaccess.h>
#include <linux/cleanup.h>

struct mxm_file {
	struct mxm_dev *mxm;
	// other stuff will go here eventually
};

int mxm_open(struct inode *inode, struct file *file)
{
	struct mxm_dev *pdev =
		container_of(file->private_data, struct mxm_dev, miscdev);
	struct mxm_file *mfile = NULL;

	mfile = kzalloc_obj(struct mxm_file, GFP_KERNEL);
	if (!mfile)
		return -ENOMEM;

	mfile->mxm = pdev;
	file->private_data = mfile;

	return 0;
}

int mxm_release(struct inode *inode, struct file *file)
{
	struct mxm_file *mfile = file->private_data;

	if (!mfile)
		return -EFAULT;

	kvfree(file->private_data);
	mfile = file->private_data = NULL;

	return 0;
}

long mxm_ioctl(struct file *file, unsigned int cmd, unsigned long arg)
{
	struct mxm_file *mfile = file->private_data;

	if (!mfile)
		return -EFAULT;

	switch (cmd) {
	case MXM_IOC_INFO: {
		struct mxm_info info = {};

		info.abi_version = MXM_ABI_VERSION;
		info.device_id = ioread32(mfile->mxm->regs + MXM_REG_ID);
		info.flags = 0ull;

		if (copy_to_user((void __user *)arg, &info, sizeof(info)))
			return -EFAULT;

		return 0;
	}
	case MXM_IOC_LIVENESS: {
		u32 val = 0;

		if (get_user(val, (__u32 __user *)arg))
			return -EFAULT;

		iowrite32(val, mfile->mxm->regs + MXM_REG_LIVENESS);
		val = ioread32(mfile->mxm->regs + MXM_REG_LIVENESS);

		if (put_user(val, (__u32 __user *)arg))
			return -EFAULT;

		return 0;
	}
	case MXM_IOC_COMPUTE: {
		u32 val = 0;
		int result = 0;

		if (get_user(val, (__u32 __user *)arg))
			return -EFAULT;

		scoped_cond_guard(mutex_intr, return -ERESTARTSYS,
				  &mfile->mxm->compute_lock)
		{
			reinit_completion(&mfile->mxm->compute_done);
			iowrite32(MXM_COMPUTE_STATUS_BIT_RAISE_ON_COMPLETION,
				  mfile->mxm->regs + MXM_REG_STATUS);
			iowrite32(val, mfile->mxm->regs + MXM_REG_COMPUTE);
			result = wait_for_completion_interruptible_timeout(
				&mfile->mxm->compute_done, HZ);
			if (result <= 0)
				return (result == 0) ? -ETIMEDOUT :
						       -ERESTARTSYS;
			val = ioread32(mfile->mxm->regs + MXM_REG_COMPUTE);
			result = 0;
		}

		if (put_user(val, (__u32 __user *)arg))
			return -EFAULT;

		return 0;
	}
	default:
		break;
	}
	return -ENOTTY;
}
