#pragma once

#include <stdio.h>
#include <unistd.h>

#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

#include "tcdl_api.h"

// unique auto tiny compute device handle
struct AutoTCDH {
  AutoTCDH() = default;
  explicit AutoTCDH(tcdl_handle h) : h(h) {}
  AutoTCDH(const AutoTCDH&) = delete;
  AutoTCDH& operator=(const AutoTCDH&) = delete;
  AutoTCDH(AutoTCDH&& o) noexcept : h(o.unhand()) {}
  AutoTCDH& operator=(AutoTCDH&& o) noexcept {
    if (this != &o) {
      reset();
      h = o.unhand();
    }
    return *this;
  }
  tcdl_handle unhand() {
    auto rh = h;
    h = nullptr;
    return rh;
  }
  ~AutoTCDH() { reset(); }
  operator tcdl_handle() const { return h; }
  void reset() {
    if (h) {
      tcdl_destroy_device(h);
    }
    h = nullptr;
  }
private:
  tcdl_handle h = nullptr;
};

inline AutoTCDH create_tcdh(int devIdx = 0, tcdl_info* pinfo = nullptr) {
  auto h = tcdl_handle(nullptr);
  if (tcdl_create_device(devIdx, &h, pinfo) != TCDL_OK) {
    fprintf(stderr, "tcdl_create_device(%d,...) failed.\n", devIdx);
    return {};
  }
  return AutoTCDH(h);
}

inline const char* boolstr(bool v) { return v ? "true" : "false"; }

extern bool test_functionality(void);
