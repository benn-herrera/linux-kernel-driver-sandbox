// A fake implementation of support.KITCHEN_SINK's API, built as libxy.so for the
// compiled checks: the C++ consumer and the Lua module run against it.
#define XY_IMPL
#include "xy_api.h"
#undef XY_IMPL

#include <cstdint>
#include <cstdlib>
#include <cstring>

struct xy_port_opaque {
  uint32_t unit;
  bool open;
};

struct xy_link_opaque {
  int unused;
};

namespace {
xy_port_opaque slots[4];
xy_link_opaque the_link;
}  // namespace

XY_API xy_status xy_open_port(uint32_t unit, xy_port* pport, xy_stats* pstats, uint32_t* generation, xy_wrap* pwrap) {
  if (unit == 99) {
    return XY_ERR_BUSY;
  }
  for (xy_port_opaque& slot : slots) {
    if (slot.open) {
      continue;
    }
    slot = {unit, true};
    *pport = &slot;
    const xy_stats stats = {unit, 1ULL << 40};
    if (pstats) {
      *pstats = stats;
    }
    *generation = 7;
    pwrap->inner = stats;
    pwrap->n = 11;
    return XY_OK;
  }
  return XY_ERR_BUSY;
}

XY_API xy_status xy_destroy_port(xy_port hport) {
  if (!hport) {
    return XY_ERR_OTHER;
  }
  if (!hport->open) {
    abort();  // released twice: a finalizer firing after an explicit release
  }
  hport->open = false;
  return XY_OK;
}

XY_API xy_status xy_send(xy_port hport, const void* buf, uint64_t len) {
  (void)hport;
  return buf != nullptr && len == 4 ? XY_OK : XY_ERR_BUSY;
}

XY_API xy_status xy_spend(xy_token htoken) {
  (void)htoken;
  return XY_OK;
}

XY_API xy_status xy_recv(xy_port hport, void* pdst, uint32_t n) {
  (void)hport;
  memset(pdst, 'r', n);
  if (n > 2) {
    static_cast<char*>(pdst)[2] = '\0';
  }
  return XY_OK;
}

XY_API xy_status xy_configure(xy_port hport, const xy_stats* cfg, const uint32_t* limit, xy_mode mode, xy_token who) {
  (void)hport;
  return cfg->count == 5 && *limit == 6 && mode == XY_SLOW && who == nullptr ? XY_OK : XY_ERR_BUSY;
}

XY_API xy_status xy_stats_of(xy_port hport, xy_stats* out, uint32_t* pcount, xy_link* plink) {
  (void)hport;
  out->count = 42;
  *pcount = 43;
  *plink = &the_link;
  return XY_OK;
}

XY_API xy_status xy_open_link(xy_link* plink) {
  *plink = &the_link;
  return XY_OK;
}

XY_API xy_status xy_reset(void) {
  return XY_OK;
}
