// A consumer of support.KITCHEN_SINK's C++ wrapper, run against fake_xy.cpp's libxy.so.
// Exit codes: 0 all steps passed; 1 create(99) failure result; 2 create(3) and its cached
// out parameters; 3 send; 4 recv; 5 configure; 6 stats_of; 7 move construction; 8 move assignment;
// 9 release; 10 destructors freed the slots; 11 PRODUCT; 12 DataLink::create; 13 bump; 14 seek and tune;
// 15 annotate (an _optional struct in parameter); 16 the _to_string conversions; 17 probe (an enum out
// parameter as the C typedef, _optional memory in, scalar in, inout and out parameters); 18 echo_offset (a
// boxed scalar by value and out).
#include "xy_api.hpp"

#include <cstring>
#include <string>
#include <type_traits>
#include <utility>

static_assert(!std::is_copy_constructible_v<xy::Port>);
static_assert(!std::is_copy_assignable_v<xy::Port>);
static_assert(std::is_nothrow_move_constructible_v<xy::Port>);
static_assert(std::is_nothrow_move_assignable_v<xy::Port>);
static_assert(std::is_same_v<xy::Stats, xy_stats>);
static_assert(std::is_same_v<xy::Wrap, xy_wrap>);
static_assert(std::is_same_v<xy::Offset, xy_offset>);
static_assert(!std::is_convertible_v<uint64_t, xy::Offset>);
static_assert(std::is_same_v<std::underlying_type_t<xy::Status>, int32_t>);
static_assert(std::is_same_v<std::underlying_type_t<xy::Mode>, uint32_t>);
static_assert(std::is_same_v<decltype(xy::API_VERSION), const uint32_t>);
static_assert(std::is_same_v<decltype(xy::FEAT_A), const int32_t>);
static_assert(std::is_same_v<decltype(xy::FEAT_ALL), const uint32_t>);
static_assert(std::is_same_v<decltype(xy::NEG), const int32_t>);
static_assert(std::is_same_v<decltype(xy::MAGIC), const uint32_t>);
static_assert(int32_t(xy::Status::ErrBusy) == XY_ERR_BUSY);
static_assert(int32_t(xy::Mode::Slow) == XY_SLOW);
static_assert(xy::FEAT_ALL == XY_FEAT_ALL);
static_assert(xy::API_VERSION == XY_API_VERSION);
static_assert(int32_t(xy::NEG) == XY_NEG);
static_assert(std::is_same_v<decltype(xy::FLOOR), const int32_t>);
static_assert(xy::FLOOR == INT32_MIN);
static_assert(int32_t(xy::Status::ErrFloor) == INT32_MIN);

int main() {
  xy::Status r = xy::Status::Ok;
  if (xy::Port::create(99, &r) || r != xy::Status::ErrBusy || std::strcmp(xy::to_string(r), "ERR_AGAIN") != 0) {
    return 1;
  }

  xy::Port port = xy::Port::create(3);
  if (!port || port.pstats().count != 3 || port.generation() != 7 || port.pwrap().n != 11) {
    return 2;
  }

  const char buf[4] = {'a', 'b', 'c', 'd'};
  if (port.send(buf, 4) != xy::Status::Ok || port.send(buf, 3) != xy::Status::ErrBusy) {
    return 3;
  }

  char out[5] = {};
  if (port.recv(out, 5) != xy::Status::Ok || out[2] != 0) {
    return 4;
  }

  xy::Stats cfg{};
  cfg.count = 5;
  const uint32_t limit = 6;
  if (port.configure(cfg, limit, xy::Mode::Slow, nullptr) != xy::Status::Ok) {
    return 5;
  }

  xy::Stats st{};
  uint32_t c = 0;
  xy_link l = nullptr;
  if (port.stats_of(st, c, l) != xy::Status::Ok || st.count != 42 || c != 43 || l == nullptr) {
    return 6;
  }

  uint32_t level = 4;
  xy::Stats tally{};
  tally.count = 5;
  char data[3] = {'a', 'b', 'c'};
  if (port.bump(level, tally, data, 3) != xy::Status::Ok || level != 5 || tally.count != 10 ||
      std::memcmp(data, "bcd", 3) != 0) {
    return 13;
  }

  int64_t next = 0;
  int32_t delta = 0;
  if (port.seek(1ULL << 40) != xy::Status::Ok || port.tune(-3, -(1LL << 40), 200, 0.5, next, delta) != xy::Status::Ok ||
      next != -(1LL << 40) - 1 || delta != -4) {
    return 14;
  }

  xy::Stats note{};
  note.count = 7;
  if (port.annotate(&note) != xy::Status::Ok || port.annotate() != xy::Status::Ok) {
    return 15;
  }

  xy_mode mode = XY_FINE;
  uint32_t probe_limit = 3;
  uint32_t probe_level = 4;
  uint32_t peek = 0;
  if (port.probe(mode, nullptr, 0) != xy::Status::Ok || mode != XY_SLOW ||
      port.probe(mode, "ab", 2, &probe_limit, &probe_level, &peek) != xy::Status::Ok || probe_level != 5 ||
      peek != 9 || port.probe(mode, "abc", 3) != xy::Status::ErrBusy) {
    return 17;
  }

  xy::Offset moved_to{};
  if (port.echo_offset(xy::Offset{1ULL << 40}, moved_to) != xy::Status::Ok || moved_to.value != 1ULL << 40) {
    return 18;
  }

  xy::Port moved = std::move(port);
  if (port || !moved) {
    return 7;
  }

  xy::Port other = xy::Port::create(4);
  other = std::move(moved);
  if (moved || !other || other.generation() != 7) {
    return 8;
  }

  if (other.release() != xy::Status::Ok || other || other.release() != xy::Status::ErrOther) {
    return 9;
  }

  {
    xy::Port a = xy::Port::create(1);
    xy::Port b = xy::Port::create(2);
    xy::Port d = xy::Port::create(3);
    xy::Port e = xy::Port::create(4);
    if (!a || !b || !d || !e) {
      return 10;
    }
  }
  if (!xy::Port::create(1)) {
    return 10;
  }

  if (std::strcmp(xy::PRODUCT, "xy widget") != 0) {
    return 11;
  }

  if (!xy::DataLink::create()) {
    return 12;
  }

  if (std::strcmp(xy::to_string(xy::Mode::Slow), "SLOW") != 0 ||
      std::strcmp(xy::to_string(xy::Status(12345)), "UNKNOWN_STATUS") != 0 || xy::access_to_string(3) != "ACC_A|ACC_B" ||
      xy::access_to_string(1) != "ACC_A" || xy::access_to_string(0) != "NONE" || xy::access_to_string(9) != "ACC_A|0x8" ||
      xy::access_to_string(-1) != "ACC_A|ACC_B|0xfffffffc" || xy::limit_to_string(16) != "MAX_UNITS" ||
      xy::limit_to_string(xy::NEG) != "NEG" || xy::limit_to_string(xy::FLOOR) != "FLOOR" ||
      xy::limit_to_string(99) != "UNKNOWN") {
    return 16;
  }
  return 0;
}
