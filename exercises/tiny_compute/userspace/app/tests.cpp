#include "common.h"

namespace {

bool test_info(tcdl_handle h, const tcdl_info& info) {
  if (!h) {
    return false;
  }
  printf("API version: 0x%08x\n", info.api_version);
  printf("device index: %u\n", info.device_idx);
  printf("dma buf size: %lu\n", info.dma_buf_size);
  printf("dma alignment: %u\n", info.dma_alignment);
  printf("capabilitiy flags: 0x%08x\n", info.device_caps);

  bool result = info.api_version && info.dma_buf_size && info.dma_alignment && info.device_caps;
  if (!result) {
    fprintf(stderr, "invalid tcdl_info values. all values besides index expected to be non-zero.\n");
  }
  return result;
}

bool test_compute(tcdl_handle h, const tcdl_info& info) {
  if (!h) {
    return false;
  }

  if (!(info.device_caps & TCDL_CAP_COMPUTE)) {
    fprintf(stderr, "device cap TCDL_CAP_COMPUTE(0x%x) expected, but missing.\n", TCDL_CAP_COMPUTE);
    return false;
  }

 	static constexpr uint32_t kFactArg = 6;
 	static constexpr uint32_t kFactVal = 6 * 5 * 4 * 3 * 2;
  uint32_t fact = 0;
  const auto tr = tcdl_compute_factorial(h, kFactArg, &fact);
  if (tr != TCDL_OK) {
    fprintf(stderr, "compute_factorial returned error %u\n", unsigned(tr));
    return false;
  }

 	const bool result = fact == kFactVal;
 	printf("factorial(%u): %u success: %s\n", kFactArg, fact, boolstr(result));
 	if (!result) {
 	  fprintf(stderr, "expected compute factorial(%u) to produce %u\n", kFactArg, kFactVal);
 	}
  return result;
}

bool test_dma_round_trip(tcdl_handle h, const tcdl_info& info) {
  if (!h) {
    return false;
  }
  bool result = true;

  if ((info.device_caps & TCDL_CAP_DMA_READ_WRITE) != TCDL_CAP_DMA_READ_WRITE) {
    fprintf(stderr, "DMA read/write capabilities expected but one or both missing.\n");
    return false;
  }

  if (!info.dma_buf_size || !info.dma_alignment) {
    fprintf(stderr, "DMA buf size and alignment both expected to be non-zero.\n");
    return false;
  }

  using namespace std;
  // cap out at 16K - max buf size or 16k are going to be aligned for this device.
  auto pattern = vector<uint16_t>(min(info.dma_buf_size, (1ul << 14)) / sizeof(uint16_t));
  for (size_t i = 0, e = pattern.size() - 1; i <= e; ++i) {
    pattern[e - i] = uint16_t(i);
  }

  auto tr = tcdl_dma_to_device(h, pattern.data(), 0x0ul, pattern.size() * sizeof(pattern[0]));
  if (tr != TCDL_OK) {
    fprintf(stderr, "dma to device failed.\n");
    return false;
  }

  auto readback = vector<uint16_t>(pattern.size(), 0xffff);
  tr = tcdl_dma_from_device(h, readback.data(), 0x0ul, readback.size() * sizeof(readback[0]));
  if (tr != TCDL_OK) {
    fprintf(stderr, "dma from device failed.\n");
    return false;
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

  tcdl_info info{};

  // continuous session
  printf("*** single continuous session check ***\n");
  {
  	auto tcdh = create_tcdh(0, &info);
    result = test_info(tcdh, info) && result;
  	result = test_compute(tcdh, info) && result;
  	result = test_dma_round_trip(tcdh, info) && result;
  }
  printf("\n");
  // individual accesses
  printf("*** separate transactions session check ***\n");
  {
    info = {};
    result = test_info(create_tcdh(0, &info), info) && result;
    info = {};
   	result = test_compute(create_tcdh(0, &info), info) && result;
    info = {};
   	result = test_dma_round_trip(create_tcdh(0, &info), info) && result;
  }
  // verify 2nd device works at all.
  info = {};
 	result = test_info(create_tcdh(1, &info), info) && result;

	return result;
}
