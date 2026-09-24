/*
Tiny Compute Device Lib C API header
!NOTE!: This file is kept luajit ffi friendly. nothing in macros makes it across the barrier.
*/
#pragma once

#include <stdint.h>

#if defined(__cplusplus)
# define TCDL_C_API extern "C"
#else
# define TCDL_C_API
#endif

#if defined(TCDL_IMPL)
# define TCDL_API TCDL_C_API __attribute__((visibility("default")))
#else
# define TCDL_API TCDL_C_API
#endif

enum {
  TCDL_API_VERSION = (0x00 << 24) | (0x01 << 16) | (0x00 << 8) | (0x00 << 0)
};

enum {
  TCDL_CAP_COMPUTE = (1u << 0),
  TCDL_CAP_DMA_READ = (1u << 1),
  TCDL_CAP_DMA_WRITE = (1u << 2),
  TCDL_CAP_DMA_READ_WRITE = TCDL_CAP_DMA_READ | TCDL_CAP_DMA_WRITE,
  TCDL_CAP_ALL = TCDL_CAP_COMPUTE | TCDL_CAP_DMA_READ_WRITE
};

enum tcdl_result {
  TCDL_OK = 0,
  TCDL_ERR_NO_DEVICE = 1,
  TCDL_ERR_INVALID_HANDLE = 2,
  TCDL_ERR_INVALID_ADDRESS = 3,
  TCDL_ERR_TIMEDOUT = 4,
  TCDL_ERR_DEVICE_DEAD = 5,
  TCDL_ERR_COMM_FAILED = 6,
  TCDL_ERR_UNKNOWN = 0x7fffffff,
};
typedef enum tcdl_result tcdl_result;

struct tcdl_opaque;
typedef struct tcdl_opaque* tcdl_handle;

struct tcdl_info {
	uint32_t api_version;   /* TCDL_API_VERSION at build time */
	uint32_t device_idx;    /* device index passed to create_device */
	uint64_t dma_buf_size;  /* device memory capacity in bytes */
	uint32_t dma_alignment; /* device address alignment and transfer granularity */
	uint32_t device_caps;   /* combination of TCDL_CAP_* */
};
typedef struct tcdl_info tcdl_info;

/* pinfo can be null */
TCDL_API tcdl_result tcdl_create_device(uint32_t index, tcdl_handle* phtcd, tcdl_info* pinfo);
TCDL_API tcdl_result tcdl_check_alive(tcdl_handle htcd);
TCDL_API tcdl_result tcdl_compute_factorial(tcdl_handle htcd, uint32_t arg, uint32_t* pfact);
/* dst_device_offset and count must be multiples of tcdl_info.dma_alignment */
TCDL_API tcdl_result tcdl_dma_to_device(tcdl_handle htcd, const void* psrc, uint64_t dst_device_offset, uint64_t count);
/* src_device_offset and count must be multiples of tcdl_info.dma_alignment */
TCDL_API tcdl_result tcdl_dma_from_device(tcdl_handle htcd, void* pdst, uint64_t src_device_offset, uint64_t count);
TCDL_API tcdl_result tcdl_destroy_device(tcdl_handle htcd);
