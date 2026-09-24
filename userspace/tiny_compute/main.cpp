/*
 * userspace test of tiny_compute driver ABI
 */

#include "common.h"

int main(void) {
  int result = 0;
  result |= test_functionality() ? 0 : 1 << 0;
  result |= test_resilience() ? 0 : 1 << 1;
  return result;
}
