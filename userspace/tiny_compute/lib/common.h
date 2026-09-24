#pragma once

#include <tiny_compute/tcd_ioctl.h>

#include <fcntl.h>
#include <stdio.h>
#include <sys/errno.h>
#include <sys/ioctl.h>
#include <unistd.h>

#include <algorithm>
#include <array>
#include <cstdint>
#include <cstring>
#include <map>
#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

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

inline AutoFD open_tcd(int devIdx = 0) {
  std::string devPath = "/dev/tiny_compute" + std::to_string(devIdx);
  auto afd = AutoFD(open(devPath.c_str(), O_RDWR|O_SYNC));
  if (afd > 0) {
    printf("opened device %s\n", devPath.c_str());
  } else {
    fprintf(stderr, "failed opening device %s: %s\n", devPath.c_str(), strerror(errno));
  }
  return afd;
}

#define IOC_PARAM(V) ((unsigned long)&V)

inline const char* boolstr(bool v) {
  return v ? "true" : "false";
}

extern bool test_functionality(void);
extern bool test_resilience(void);
