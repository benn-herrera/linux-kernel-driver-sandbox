#pragma once

#include <tiny_compute/driver/tcd_ioctl.h>

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

// unique auto file descriptor
struct AutoFD {
  AutoFD() = default;
  explicit AutoFD(int fd) : fd(fd) {}
  AutoFD(const AutoFD&) = delete;
  AutoFD& operator=(const AutoFD&) = delete;
  AutoFD(AutoFD&& o) noexcept : fd(o.unhand()) {}
  AutoFD& operator=(AutoFD&& o) noexcept {
    if (this != &o) {
      reset();
      fd = o.unhand();
    }
    return *this;
  }
  int unhand() {
    const auto rfd = fd;
    fd = -1;
    return rfd;
  }
  ~AutoFD() { reset(); }
  operator int() const { return fd; }
  void reset() {
    if (fd >= 0) {
      close(fd);
    }
    fd = -1;
  }
private:
  int fd = -1;
};

#define IOC_PARAM(V) ((unsigned long)&V)
