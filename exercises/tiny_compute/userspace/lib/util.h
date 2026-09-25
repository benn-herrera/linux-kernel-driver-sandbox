#pragma once

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
