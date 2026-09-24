#include "common.h"

namespace {

bool test_adv_info(int fd) {
  if (fd < 0) {
    return false;
  }
  bool result = true;

  // TODO: the rest!
  //
  return result;
}

bool test_adv_live(int fd) {
  if (fd < 0) {
    return false;
  }
  bool result = true;

  // TODO: the rest!
  //
  return result;
}

bool test_adv_compute(int fd) {
  if (fd < 0) {
    return false;
  }
  bool result = true;

  // TODO: the rest!
  //
  return result;
}

bool test_adv_dma_from_dev(int fd) {
  if (fd < 0) {
    return false;
  }
  bool result = true;

  // TODO: the rest!
  //
  return result;
}

bool test_adv_dma_to_dev(int fd) {
  if (fd < 0) {
    return false;
  }
  bool result = true;

  // TODO: the rest!
  //
  return result;
}

} // namespace

//
// tests with adversarial usage patterns to see if it blows up
//
bool test_resilience() {
  bool result = true;

 	result = test_adv_info(open_tcd()) && result;
 	result = test_adv_live(open_tcd()) && result;
 	result = test_adv_compute(open_tcd()) && result;
 	result = test_adv_dma_from_dev(open_tcd()) && result;
 	result = test_adv_dma_to_dev(open_tcd()) && result;

  return true;
}
