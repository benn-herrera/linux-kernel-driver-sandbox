/*
 * implementation of userspace tests of Tiny Compute Device Library API
 */
#include "common.h"
#include <stdio.h>
#include <unistd.h>
#include <cstdint>
#include <cstring>
#include <vector>

// binding.tcdl_api.hpp is generated from api_def/tcdl_api.adef.toml by api_gen
// see vdev/justfile recipe 'generate'
#include "tcdl_api.hpp"

namespace {

const char* boolstr(bool v) { return v ? "true" : "false"; }

bool test_info(tcdl::Device& d) {
  if (!d) {
    return false;
  }
  const auto& info = d.info();
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

bool test_compute(tcdl::Device& d) {
  if (!d) {
    return false;
  }
  const auto& info = d.info();

  if (!(info.device_caps & tcdl::CAP_COMPUTE)) {
    fprintf(stderr, "device cap TCDL_CAP_COMPUTE(0x%x) expected, but missing.\n", tcdl::CAP_COMPUTE);
    return false;
  }

 	static constexpr uint32_t kFactArg = 6;
 	static constexpr uint32_t kFactVal = 6 * 5 * 4 * 3 * 2;
  uint32_t fact = 0;
  const auto tr = d.compute_factorial(kFactArg, fact);
  if (tr != tcdl::Result::Ok) {
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

bool test_dma_round_trip(tcdl::Device& d) {
  if (!d) {
    return false;
  }
  const auto& info = d.info();
  bool result = true;

  if ((info.device_caps & tcdl::CAP_DMA_READ_WRITE) != tcdl::CAP_DMA_READ_WRITE) {
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

  auto tr = d.dma_to_device(pattern.data(), 0x0ul, pattern.size() * sizeof(pattern[0]));
  if (tr != tcdl::Result::Ok) {
    fprintf(stderr, "dma to device failed.\n");
    return false;
  }

  auto readback = vector<uint16_t>(pattern.size(), 0xffff);
  tr = d.dma_from_device(readback.data(), 0x0ul, readback.size() * sizeof(readback[0]));
  if (tr != tcdl::Result::Ok) {
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

  // continuous session
  printf("*** single continuous session check ***\n");
  {
    tcdl::Result cres{};
  	auto d = tcdl::Device::create(0, &cres);
    if (!d) {
      fprintf(stderr, "failed creating device: %s(%u).\n", tcdl::to_string(cres), unsigned(cres));
      return false;
    }
    result = test_info(d) && result;
  	result = test_compute(d) && result;
  	result = test_dma_round_trip(d) && result;
  }
  printf("\n");
  // individual accesses
  printf("*** separate transactions session check ***\n");
  {
    auto d = tcdl::Device::create(0);
    result = test_info(d) && result;
  }
  {
    auto d = tcdl::Device::create(0);
   	result = test_compute(d) && result;
  }
  {
    auto d = tcdl::Device::create(0);
   	result = test_dma_round_trip(d) && result;
  }
  // verify 2nd device works at all.
  {
    auto d = tcdl::Device::create(1);
   	result = test_info(d) && result;
  }

	return result;
}
