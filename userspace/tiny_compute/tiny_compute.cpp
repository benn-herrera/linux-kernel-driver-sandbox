// SPDX-License-Identifier: GPL-2.0
/*
 * userspace test of tiny_compute driver ABI
 */

#include <unistd.h>
#include <stdio.h>
#include <cstring>
#include <cstdint>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <sys/errno.h>

#include <tiny_compute/tcd_ioctl.h>

struct AutoFD {
  int fd = -1;
  AutoFD(int fd) : fd(fd) {}
  operator int() const { return fd; }
  ~AutoFD() {
    if (fd >= 0) {
      close(fd);
      fd = -1;
    }
  }
};

#define IOC_PARAM(V) ((unsigned long)&V)

const char* boolstr(bool v) {
  return v ? "true" : "false";
}

int main(void) {
	AutoFD fd = open("/dev/tiny_compute", O_RDWR|O_SYNC);
	if (fd < 0) {
	  fprintf(stderr, "failed opening device: %s\n", strerror(errno));
	  return 1;
	}

	int result = 0;

	{
    tcd_info tcd{};
    if (ioctl(fd, TCD_IOC_INFO, IOC_PARAM(tcd)) < 0) {
      fprintf(stderr, "ioctl failed getting device info: %s\n", strerror(errno));
      result = 1;
    } else {
      printf("ABI version: 0x%08x\n", tcd.abi_version);
      printf("device ID: 0x%08x\n", tcd.device_id);
      printf("capabilitiy flags: 0x%016llx\n", tcd.flags);
      if (!tcd.abi_version || !tcd.device_id) {
        fprintf(stderr, "invalid abi_version and/or device_id - both expected to be non-zero.\n");
        result = 1;
      }
    }
	}

  {
    static constexpr uint32_t kLiveCheck = 0x80800101;
    uint32_t alive = kLiveCheck;
    if (ioctl(fd, TCD_IOC_LIVENESS, IOC_PARAM(alive))) {
      fprintf(stderr, "ioctl failed running liveness check: %s\n", strerror(errno));
      result = 1;
    } else {
      const bool isAlive = alive == ~kLiveCheck;
      printf("live in: 0x%08x, live out: 0x%08x, alive: %s\n", kLiveCheck, alive, boolstr(isAlive));
      if (!isAlive) {
        fprintf(stderr, "device liveness check failed (expected live out bits to have been inverted from live in)\n");
        result = 1;
      }
    }
  }

  {
  	static constexpr uint32_t kFactArg = 6;
  	static constexpr uint32_t kFactVal = 6 * 5 * 4 * 3 * 2;
  	uint32_t factParam = kFactArg;
  	if (ioctl(fd, TCD_IOC_COMPUTE, IOC_PARAM(factParam))) {
      fprintf(stderr, "ioctl failed running compute [factorial(%d)]: %s\n", factParam, strerror(errno));
      result = 1;
  	} else {
     	const bool factCorrect = factParam == kFactVal;
     	printf("factorial(%u): %u success: %s\n", kFactArg, factParam, boolstr(factCorrect));
     	if (!factCorrect) {
     	  fprintf(stderr, "expected compute factorial(%u) to produce %u\n", kFactArg, kFactVal);
        result = 1;
     	}
    }
  }

	return result;
}
