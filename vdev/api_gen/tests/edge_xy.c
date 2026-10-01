// A bare C caller of support.KITCHEN_SINK's library, run against fake_xy.rs's libxy.so: what the
// Rust relay hands the implementation for what no binding sends. fake_xy.rs names the entry it
// answers each case with.
// Exit codes: 0 every case answered as expected; 1 null for a non-optional out answers ERR_FLOOR;
// 2 that call claimed no slot: four ports still open; 3 null for a non-optional in struct answers
// ERR_FLOOR; 4 a count above isize::MAX answers ERR_UNSUPPORTED; 5 an out buffer reaches the
// implementation zeroed, whatever the caller's memory held; 6 a non-null buffer with a count of 0
// arrives present and empty, so ERR_BUSY; 7 aliased pointers are copied in before the call and
// written back after it in parameter order; 8 an enum value no entry names answers ERR_AGAIN;
// 9 null for probe's pmode is still ok; 10 outs are written back after a failing call; 11 an out
// starts from its default, not the caller's value; 12 a null in buffer with a nonzero count
// answers ERR_UNSUPPORTED; 13 null for a non-optional inout answers ERR_FLOOR; 14 a null out
// buffer with a nonzero count answers ERR_UNSUPPORTED; 15 so does a null inout buffer.
// Only send's count is u64: recv's and bump's are u32, which cannot exceed isize::MAX on a 64-bit
// target, so case 4 is the only count above it.
// With the argument `panic`, calls xy_seek(NULL, UINT64_MAX), whose implementation panics: the
// process aborts, so returning at all exits 99.
#include "xy_api.h"

#include <stdint.h>
#include <string.h>

static int cases(void) {
  xy_port ports[4];
  xy_stats stats;
  uint32_t generation;
  xy_wrap wrap;

  if (xy_open_port(3, NULL, NULL, NULL, NULL) != XY_ERR_FLOOR) {
    return 1;
  }
  for (int i = 0; i < 4; ++i) {
    if (xy_open_port(3, &ports[i], &stats, &generation, &wrap) != XY_OK || generation != 7 || wrap.n != 11) {
      return 2;
    }
  }
  for (int i = 1; i < 4; ++i) {
    if (xy_destroy_port(ports[i]) != XY_OK) {
      return 2;
    }
  }
  xy_port port = ports[0];

  const uint32_t limit = 6;
  if (xy_configure(port, NULL, &limit, XY_SLOW, NULL) != XY_ERR_FLOOR) {
    return 3;
  }

  const char four[4] = {'a', 'b', 'c', 'd'};
  if (xy_send(port, four, (uint64_t)1 << 63) != XY_ERR_UNSUPPORTED) {
    return 4;
  }

  // fake_xy.rs answers ERR_OTHER to a buffer that arrives holding anything but zeros
  char dirty[8];
  memset(dirty, 0xaa, sizeof dirty);
  if (xy_recv(port, dirty, sizeof dirty) != XY_OK) {
    return 5;
  }
  char buf[8];
  if (xy_recv(port, buf, sizeof buf) != XY_OK || memcmp(buf, "rr\0rrrrr", sizeof buf) != 0) {
    return 5;
  }

  if (xy_send(port, four, 0) != XY_ERR_BUSY) {
    return 6;
  }

  // level aliases tally.count: each copy is bumped on its own, then level (5 + 1) is written back
  // before tally (count 5 * 2), so the count ends 10. Under C++'s in-place writes it would be 12.
  xy_stats tally = {.count = 5, .bytes = 0};
  char data[3] = {'a', 'b', 'c'};
  if (xy_bump(port, &tally.count, &tally, data, sizeof data) != XY_OK || tally.count != 10 ||
      memcmp(data, "bcd", sizeof data) != 0) {
    return 7;
  }
  // limit aliases level: limit is read before the call, so it is still 3 when checked.
  uint32_t shared = 3;
  xy_mode mode = XY_FINE;
  if (xy_probe(port, &mode, NULL, 0, &shared, &shared, NULL) != XY_OK || shared != 4 || mode != XY_SLOW) {
    return 7;
  }

  const xy_stats cfg = {.count = 5, .bytes = 0};
  if (xy_configure(port, &cfg, &limit, 7, NULL) != XY_ERR_AGAIN) {
    return 8;
  }

  if (xy_probe(port, NULL, NULL, 0, NULL, NULL, NULL) != XY_OK) {
    return 9;
  }

  // the fake writes both outs, then answers ERR_BUSY for delta 0
  int64_t next = 0;
  int32_t delta = 0;
  if (xy_tune(port, 0, 5, 200, 0.5, &next, &delta) != XY_ERR_BUSY || next != 4 || delta != -1) {
    return 10;
  }

  // the fake writes only count
  xy_stats seen = {.count = 1, .bytes = 99};
  uint32_t count;
  xy_link link;
  if (xy_stats_of(port, &seen, &count, &link) != XY_OK || seen.count != 42 || seen.bytes != 0) {
    return 11;
  }

  if (xy_send(port, NULL, 4) != XY_ERR_UNSUPPORTED) {
    return 12;
  }

  if (xy_bump(port, NULL, &tally, data, sizeof data) != XY_ERR_FLOOR) {
    return 13;
  }

  if (xy_recv(port, NULL, 8) != XY_ERR_UNSUPPORTED) {
    return 14;
  }

  uint32_t level = 1;
  if (xy_bump(port, &level, &tally, NULL, 3) != XY_ERR_UNSUPPORTED) {
    return 15;
  }

  if (xy_destroy_port(port) != XY_OK) {
    return 2;
  }
  return 0;
}

int main(int argc, char** argv) {
  if (argc > 1 && strcmp(argv[1], "panic") == 0) {
    (void)xy_seek(NULL, UINT64_MAX);
    return 99;
  }
  return cases();
}
