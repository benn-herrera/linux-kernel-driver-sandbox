/*
 * userspace test of tiny_compute driver ABI
 */

#include "common.h"

int main(void) {
  return test_functionality() ? 0 : 1;
}
