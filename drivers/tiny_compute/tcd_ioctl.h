/* SPDX-License-Identifier: GPL-2.0 */
/*
 * tcd_ioctl: user-facing ABI for device
 */
#if !defined(TCD_IOCTL_H)
#define TCD_IOCTL_H

#include <linux/ioctl.h>
#include <linux/types.h>

// enum and macro constants

#define TCD_MAKE_VERSION(MAJ, MIN, PATCH) \
	(((MAJ) << 16) | ((MIN) << 8) | (PATCH))
#define TCD_ABI_VERSION TCD_MAKE_VERSION(0, 5, 0)

#define TCD_IOC_MAGIC 0x8d /* arbitrary, unique among the tree's ioctl magics */
#define TCD_IOC_INFO _IOR(TCD_IOC_MAGIC, 0x00, struct tcd_info)
#define TCD_IOC_LIVENESS _IOWR(TCD_IOC_MAGIC, 0x01, __u32)
#define TCD_IOC_COMPUTE _IOWR(TCD_IOC_MAGIC, 0x02, __u32)
#define TCD_IOC_TEST_IRQ _IOW(TCD_IOC_MAGIC, 0x03, __u32)

// structures

// exactly 16 packed bytes.
struct tcd_info {
	__u32 abi_version; /*TCD_ABI_VERSION at build time*/
	__u32 device_id; /* device id in the registry */
	__u64 flags; /* device caps */
};

#endif /* TCD_IOCTL_H */
