// SPDX-License-Identifier: GPL-2.0
/*
 * userspace test of matx_mock driver ABI
 */

#include <unistd.h>
#include <iostream>
#include <cstring>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <sys/errno.h>

#include <matx_mock/mxm_ioctl.h>

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

int main(void) {
	AutoFD fd = open("/dev/matx_mock", O_RDWR|O_SYNC);
	if (fd < 0) {
	  std::cerr << "failed opening device: " << strerror(errno) << std::endl;
	  return 1;
	}

	mxm_info mxm;

	if (ioctl(fd, MXM_IOC_INFO, long(&mxm)) < 0) {
	  std::cerr << "ioctl failed getting device info: " << strerror(errno) << std::endl;
		return 1;
	}

	std::cout << "ABI version: " << mxm.abi_version << std::endl;
	std::cout << "device ID: " << mxm.device_id << std::endl;
	std::cout << "capabilitiy flags: " << mxm.flags << std::endl;

	return 0;
}
