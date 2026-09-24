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

bool test_func_dma_from_dev(int fd) {
  if (fd < 0) {
    return false;
  }
  bool result = true;
  // do the thing
  return result;
}

bool test_func_dma_to_dev(int fd) {
  if (fd < 0) {
    return false;
  }
  bool result = true;
  // do the thing
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
  	result = test_func_dma_from_dev(afd) && result;
  	result = test_func_dma_to_dev(afd) && result;
  }
  printf("\n");
  // individual accesses
  printf("*** separate transactions session check ***\n");
  {
   	result = test_func_info(open_tcd()) && result;
   	result = test_func_live(open_tcd()) && result;
   	result = test_func_compute(open_tcd()) && result;
   	result = test_func_dma_from_dev(open_tcd()) && result;
   	result = test_func_dma_to_dev(open_tcd()) && result;
  }

	return result;
}
