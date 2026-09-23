/* SPDX-License-Identifier: GPL-2.0 */
/*
 * mxm_ioctl: user-facing ABI for device
 */
#if !defined(MXM_IOCTL_H)
#define MXM_IOCTL_H

#include <linux/ioctl.h>
#include <linux/types.h>

// enum and macro constants

#define MXM_MAKE_VERSION(MAJ, MIN, PATCH) \
	(((MAJ) << 16) | ((MIN) << 8) | (PATCH))
#define MXM_ABI_VERSION MXM_MAKE_VERSION(0, 5, 0)

#define MXM_IOC_MAGIC 0x8d /* 0x81 + 'M' - 'A'*/
#define MXM_IOC_INFO _IOR(MXM_IOC_MAGIC, 0x00, struct mxm_info)
#define MXM_IOC_LIVENESS _IOWR(MXM_IOC_MAGIC, 0x01, __u32)
#define MXM_IOC_COMPUTE _IOWR(MXM_IOC_MAGIC, 0x02, __u32)
#define MXM_IOC_TEST_IRQ _IOW(MXM_IOC_MAGIC, 0x03, __u32)

// structures

// exactly 16 packed bytes.
struct mxm_info {
	__u32 abi_version; /*MXM_ABI_VERSION at build time*/
	__u32 device_id; /* device id in the registry */
	__u64 flags; /* device caps */
};

#endif /* MXM_IOCTL_H */
