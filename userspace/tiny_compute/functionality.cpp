#include "common.h"

namespace {

bool test_func_info(int fd) {
  if (fd < 0) {
    return false;
  }
  bool result = true;
  tcd_info tcd{};

  if (ioctl(fd, TCD_IOC_INFO, IOC_PARAM(tcd)) < 0) {
    fprintf(stderr, "ioctl failed getting device info: %s\n", strerror(errno));
    result = false;
  } else {
    printf("ABI version: 0x%08x\n", tcd.abi_version);
    printf("device ID: 0x%08x\n", tcd.device_id);
    printf("dma buf size: %llu\n", tcd.dma_buf_size);
    printf("dma alignment: %u\n", tcd.dma_alignment);
    printf("capabilitiy flags: 0x%08x\n", tcd.flags);

    result = tcd.abi_version && tcd.device_id && tcd.dma_buf_size && tcd.dma_alignment && tcd.flags;
    if (!result) {
      fprintf(stderr, "invalid tcd_info values. all values expected to be non-zero.\n");
    }
  }

  return result;
}

bool test_func_live(int fd) {
  if (fd < 0) {
    return false;
  }
  bool result = true;
  static constexpr uint32_t kLiveCheck = 0x80800101;
  uint32_t alive = kLiveCheck;

  if (ioctl(fd, TCD_IOC_LIVENESS, IOC_PARAM(alive))) {
    fprintf(stderr, "ioctl failed running liveness check: %s\n", strerror(errno));
    result = false;
  } else {
    result = alive == ~kLiveCheck;
    printf("live in: 0x%08x, live out: 0x%08x, alive: %s\n", kLiveCheck, alive, boolstr(result));
    if (!result) {
      fprintf(stderr, "device liveness check failed (expected live out bits to have been inverted from live in)\n");
    }
  }
  return result;
}

bool test_func_compute(int fd) {
  if (fd < 0) {
    return false;
  }
  bool result = true;
 	static constexpr uint32_t kFactArg = 6;
 	static constexpr uint32_t kFactVal = 6 * 5 * 4 * 3 * 2;
 	uint32_t factParam = kFactArg;

 	if (ioctl(fd, TCD_IOC_COMPUTE, IOC_PARAM(factParam))) {
     fprintf(stderr, "ioctl failed running compute [factorial(%d)]: %s\n", factParam, strerror(errno));
     result = false;
 	} else {
    	result = factParam == kFactVal;
    	printf("factorial(%u): %u success: %s\n", kFactArg, factParam, boolstr(result));
    	if (!result) {
    	  fprintf(stderr, "expected compute factorial(%u) to produce %u\n", kFactArg, kFactVal);
    	}
   }
  return result;
}

bool test_func_dma_round_trip(int fd) {
  if (fd < 0) {
    return false;
  }
  bool result = true;

  tcd_info tcd{};

  if (ioctl(fd, TCD_IOC_INFO, IOC_PARAM(tcd)) < 0) {
    fprintf(stderr, "ioctl failed getting device info: %s\n", strerror(errno));
    return false;
  }

  if ((tcd.flags & (TCD_DEVICE_CAP_DMA_READ | TCD_DEVICE_CAP_DMA_WRITE)) != (TCD_DEVICE_CAP_DMA_READ | TCD_DEVICE_CAP_DMA_WRITE)) {
    fprintf(stderr, "DMA read/write capabilities expected but one or both missing.\n");
    return false;
  }

  if (!tcd.dma_buf_size || !tcd.dma_alignment) {
    fprintf(stderr, "DMA buf size and alignment both expected to be non-zero.\n");
    return false;
  }

  using namespace std;
  // cap out at 16K - max buf size or 16k are going to be aligned for this device.
  auto pattern = vector<uint16_t>(min(tcd.dma_buf_size, (1ull << 14)) / sizeof(uint16_t));
  for (size_t i = 0, e = pattern.size() - 1; i <= e; ++i) {
    pattern[e - i] = uint16_t(i);
  }

  {
    tcd_dma_req to_dev_req{ .ubuf = uint64_t(pattern.data()), .dev_offset = 0x0ull, .count = pattern.size() * sizeof(pattern[0]) };
    if (ioctl(fd, TCD_IOC_DMA_TO_DEVICE, IOC_PARAM(to_dev_req))) {
      fprintf(stderr, "dma to device failed.\n");
      return false;
    }
  }

  auto readback = vector<uint16_t>(pattern.size(), 0xffff);
  {
    tcd_dma_req from_dev_req{ .ubuf = uint64_t(readback.data()), .dev_offset = 0x0ull, .count = readback.size() * sizeof(readback[0]) };
    if (ioctl(fd, TCD_IOC_DMA_FROM_DEVICE, IOC_PARAM(from_dev_req))) {
      fprintf(stderr, "dma from device failed.\n");
      return false;
    }
  }

  if (memcmp(readback.data(), pattern.data(), pattern.size() * sizeof(pattern[0])) != 0) {
    fprintf(stderr, "DMA round trip failed - read pattern did not match written.\n");
    result = false;
  }

  return result;
}

} // namespace

//
// test with expected usage patterns to see if it works at all
//
bool test_functionality(void) {
 	bool result = true;

  // continuous session
  printf("*** single continuous session check ***\n");
  {
  	auto afd = open_tcd();
  	result = test_func_info(afd) && result;
  	result = test_func_live(afd) && result;
  	result = test_func_compute(afd) && result;
  	result = test_func_dma_round_trip(afd) && result;
  }
  printf("\n");
  // individual accesses
  printf("*** separate transactions session check ***\n");
  {
   	result = test_func_info(open_tcd()) && result;
   	result = test_func_live(open_tcd()) && result;
   	result = test_func_compute(open_tcd()) && result;
   	result = test_func_dma_round_trip(open_tcd()) && result;
  }
  // verify 2nd device works at all.
 	result = test_func_info(open_tcd(1)) && result;


	return result;
}
