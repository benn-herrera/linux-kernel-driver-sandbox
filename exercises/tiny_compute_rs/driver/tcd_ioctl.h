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
#define TCD_IOC_DMA_FROM_DEVICE _IOW(TCD_IOC_MAGIC, 0x03, struct tcd_dma_req)
#define TCD_IOC_DMA_TO_DEVICE _IOW(TCD_IOC_MAGIC, 0x04, struct tcd_dma_req)

// if read-only a hypothetical compute operation could write to DMA for readout (i.e. compute perlin noise)
// if write-only a hypothetical compute operation could require buffer contents to produce a register-delivered result (e.g. avg lum)
// a read/write op might take a buffer at address 512 and write to address 0-512 a histogram with 16bit buckets.
// or read/write might just correspond to portable storage built into the device for general utility.

#define TCD_DEVICE_CAP_COMPUTE (1u << 0)
#define TCD_DEVICE_CAP_DMA_READ (1u << 1)
#define TCD_DEVICE_CAP_DMA_WRITE (1u << 2)

#define TCD_DEVICE_NAME_BASE "tiny_compute"

// structures

// exactly 24 bytes.
struct tcd_info {
	__u32 abi_version; /*TCD_ABI_VERSION at build time*/
	__u32 device_id; /* device id in the registry */
	__u64 dma_buf_size; /*device memory capacity in bytes*/
	__u32 dma_alignment; /*device address alignment and transfer granularity*/
	__u32 flags; /* device caps */
};

struct tcd_dma_req {
	__u64 ubuf; /*userspace buffer address*/
	__u64 dev_offset; /*byte offset into device buffer - must be tcd_info.dma_alignment aligned*/
	__u64 count; /*transfer byte count - must be multiple of tcd_info.dma_alignment*/
};

#endif /* TCD_IOCTL_H */
