#include <linux/printk.h>
#include "common.h"

int mmd_init(void) {
 	pr_info("matx_mock: loaded\n");
  return 0;
}

void mmd_exit(void) {
 	pr_info("matx_mock: unloaded\n");
}
