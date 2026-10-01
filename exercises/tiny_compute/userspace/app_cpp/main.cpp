/*
 * entry point for userspace test of Tiny Compute Device Library API
 */

#include "common.h"

int main(void) {
  return test_functionality() ? 0 : 1;
}
