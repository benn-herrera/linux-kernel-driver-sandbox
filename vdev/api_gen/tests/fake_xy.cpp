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

XY_API xy_status xy_send(xy_port hport, const void* buf, uint64_t buf_count) {
  (void)hport;
  return buf != nullptr && buf_count == 4 ? XY_OK : XY_ERR_BUSY;
}

XY_API xy_status xy_spend(xy_token htoken) {
  (void)htoken;
  return XY_OK;
}

XY_API xy_status xy_recv(xy_port hport, void* pdst, uint32_t pdst_count) {
  (void)hport;
  memset(pdst, 'r', pdst_count);
  if (pdst_count > 2) {
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

XY_API xy_status xy_bump(xy_port hport, uint32_t* level, xy_stats* tally, void* data, uint32_t data_count) {
  (void)hport;
  *level += 1;
  tally->count *= 2;
  for (uint32_t i = 0; i < data_count; ++i) {
    static_cast<uint8_t*>(data)[i] += 1;
  }
  return XY_OK;
}

XY_API xy_status xy_open_link(xy_link* plink) {
  *plink = &the_link;
  return XY_OK;
}

XY_API xy_status xy_annotate(xy_port hport, const xy_stats* note) {
  (void)hport;
  return note == nullptr || note->count == 7 ? XY_OK : XY_ERR_BUSY;
}

XY_API xy_status xy_reset(void) {
  return XY_OK;
}

XY_API xy_status xy_seek(xy_port hport, uint64_t offset) {
  (void)hport;
  return offset == 1ULL << 40 ? XY_OK : XY_ERR_BUSY;
}

XY_API xy_status xy_tune(xy_port hport, int32_t delta, int64_t big, uint8_t small, double scale, int64_t* pnext,
                         int32_t* pdelta) {
  (void)hport;
  *pnext = big - 1;
  *pdelta = delta - 1;
  return delta == -3 && big == -(1LL << 40) && small == 200 && scale == 0.5 ? XY_OK : XY_ERR_BUSY;
}

XY_API xy_status xy_probe(xy_port hport, xy_mode* pmode, const void* payload, uint32_t payload_count,
                          const uint32_t* limit, uint32_t* level, uint32_t* ppeek) {
  (void)hport;
  *pmode = XY_SLOW;
  if (level) {
    *level += 1;
  }
  if (ppeek) {
    *ppeek = 9;
  }
  const bool payload_ok = payload == nullptr ? payload_count == 0 : payload_count == 2;
  return payload_ok && (limit == nullptr || *limit == 3) ? XY_OK : XY_ERR_BUSY;
}

XY_API xy_status xy_echo_offset(xy_port hport, xy_offset pos, xy_offset* ppos) {
  (void)hport;
  *ppos = pos;
  return XY_OK;
}
