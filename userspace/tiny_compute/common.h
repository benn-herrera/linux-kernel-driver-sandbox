#pragma once

#include <unistd.h>
#include <stdio.h>
#include <cstring>
#include <cstdint>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <sys/errno.h>

#include <tiny_compute/tcd_ioctl.h>

// owns one descriptor; move-only so a copy can never close it twice
struct AutoFD {
  int fd = -1;
  AutoFD() = default;
  explicit AutoFD(int fd) : fd(fd) {}
  AutoFD(const AutoFD&) = delete;
  AutoFD& operator=(const AutoFD&) = delete;
  AutoFD(AutoFD&& o) noexcept : fd(o.fd) { o.fd = -1; }
  AutoFD& operator=(AutoFD&& o) noexcept {
    if (this != &o) {
      reset();
      fd = o.fd;
      o.fd = -1;
    }
    return *this;
  }
  ~AutoFD() { reset(); }
  operator int() const { return fd; }
  void reset() {
    if (fd >= 0) {
      close(fd);
    }
    fd = -1;
  }
};

inline AutoFD open_tcd(const char* devPath=nullptr) {
  auto afd = AutoFD(open(devPath ? devPath : "/dev/tiny_compute", O_RDWR|O_SYNC));
  if (afd < 0) {
    fprintf(stderr, "failed opening device: %s\n", strerror(errno));
  }
  return afd;
}

#define IOC_PARAM(V) ((unsigned long)&V)

inline const char* boolstr(bool v) {
  return v ? "true" : "false";
}

extern bool test_functionality(void);
extern bool test_resilience(void);
