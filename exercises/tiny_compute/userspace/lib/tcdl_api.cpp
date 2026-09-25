
#define TCDL_IMPL
#include "tcdl_api.h"
#undef TCDL_IMPL
#include "util.h"

#define IOC_PARAM(V) ((unsigned long)&V)

namespace {

AutoFD open_tcd(int devIdx = 0) {
  std::string devPath = std::string("/dev/") + TCD_DEVICE_NAME_BASE + std::to_string(devIdx);
  return AutoFD(open(devPath.c_str(), O_RDWR|O_SYNC));
}

static constexpr auto kHandleObfusc = intptr_t(0x00867530900);

tcdl_handle fd2h(int fd) {
  return tcdl_handle(intptr_t(fd) ^ kHandleObfusc);
}

int h2fd(tcdl_handle h) {
  return int(intptr_t(h) ^ kHandleObfusc);
}

} // namespace

tcdl_result tcdl_create_device(uint32_t index, tcdl_handle* phtcd, tcdl_info* pinfo) {
  // pin to tcd_ioctl values
  static_assert(TCDL_CAP_COMPUTE == TCD_DEVICE_CAP_COMPUTE);
  static_assert(TCDL_CAP_DMA_READ == TCD_DEVICE_CAP_DMA_READ);
  static_assert(TCDL_CAP_DMA_WRITE == TCD_DEVICE_CAP_DMA_WRITE);

  if (!phtcd) {
    return TCDL_ERR_INVALID_ADDRESS;
  }

  auto fd = open_tcd(index);
  *phtcd = nullptr;

  if (fd < 0) {
    return TCDL_ERR_NO_DEVICE;
  }

  tcd_info tcd{};
  if (ioctl(fd, TCD_IOC_INFO, IOC_PARAM(tcd)) < 0) {
    return TCDL_ERR_COMM_FAILED;
  }

  if (pinfo) {
    pinfo->api_version = TCDL_API_VERSION;
    pinfo->device_idx = index;
    pinfo->dma_buf_size = tcd.dma_buf_size;
    pinfo->dma_alignment = tcd.dma_alignment;
    pinfo->device_caps = tcd.flags;
  }

  *phtcd = fd2h(fd.unhand());
  return TCDL_OK;
}

tcdl_result tcdl_check_alive(tcdl_handle htcd) {
  if (!htcd) {
    return TCDL_ERR_INVALID_HANDLE;
  }
  const auto fd = h2fd(htcd);
  static constexpr uint32_t kLiveCheck = 0x80800101;
  uint32_t alive = kLiveCheck;

  if (ioctl(fd, TCD_IOC_LIVENESS, IOC_PARAM(alive))) {
    return TCDL_ERR_COMM_FAILED;
  }
  return alive == ~kLiveCheck ? TCDL_OK : TCDL_ERR_DEVICE_DEAD;
}

tcdl_result tcdl_compute_factorial(tcdl_handle htcd, uint32_t arg, uint32_t* pfact) {
  if (!htcd) {
    return TCDL_ERR_INVALID_HANDLE;
  }
  if (!pfact) {
    return TCDL_ERR_INVALID_ADDRESS;
  }
  const auto fd = h2fd(htcd);
 	auto result = ioctl(fd, TCD_IOC_COMPUTE, IOC_PARAM(arg));
  if (result) {
    return errno == ETIMEDOUT ? TCDL_ERR_TIMEDOUT : (errno == EOPNOTSUPP ? TCDL_ERR_UNSUPPORTED : TCDL_ERR_COMM_FAILED);
  }
  *pfact = arg;
  return TCDL_OK;
}

tcdl_result tcdl_dma_to_device(tcdl_handle htcd, const void* psrc, uint64_t dst_device_offset, uint64_t count) {
  if (!htcd) {
    return TCDL_ERR_INVALID_HANDLE;
  }
  if (!psrc) {
    return TCDL_ERR_INVALID_ADDRESS;
  }
  const auto fd = h2fd(htcd);

  tcd_dma_req to_dev_req{ .ubuf = uint64_t(psrc), .dev_offset = dst_device_offset, .count = count };
  if (ioctl(fd, TCD_IOC_DMA_TO_DEVICE, IOC_PARAM(to_dev_req))) {
    return errno == ETIMEDOUT ? TCDL_ERR_TIMEDOUT : (errno == EOPNOTSUPP ? TCDL_ERR_UNSUPPORTED : TCDL_ERR_COMM_FAILED);
  }

  return TCDL_OK;
}

tcdl_result tcdl_dma_from_device(tcdl_handle htcd, void* pdst, uint64_t src_device_offset, uint64_t count) {
  if (!htcd) {
    return TCDL_ERR_INVALID_HANDLE;
  }
  if (!pdst) {
    return TCDL_ERR_INVALID_ADDRESS;
  }
  const auto fd = h2fd(htcd);

  tcd_dma_req from_dev_req{ .ubuf = uint64_t(pdst), .dev_offset = src_device_offset, .count = count };
  if (ioctl(fd, TCD_IOC_DMA_FROM_DEVICE, IOC_PARAM(from_dev_req))) {
    return errno == ETIMEDOUT ? TCDL_ERR_TIMEDOUT : (errno == EOPNOTSUPP ? TCDL_ERR_UNSUPPORTED : TCDL_ERR_COMM_FAILED);
  }

  return TCDL_OK;
}

tcdl_result tcdl_destroy_device(tcdl_handle htcd) {
  if (!htcd) {
    return TCDL_ERR_INVALID_HANDLE;
  }
  const auto fd = h2fd(htcd);
  if (close(fd)) {
    return TCDL_ERR_INVALID_HANDLE;
  }
  return TCDL_OK;
}
