// SPDX-License-Identifier: GPL-2.0
/*
 * main: driver entry point
 */
#include "common.h"

static int __init tiny_compute_init(void)
{
	return tcd_init();
}

static void __exit tiny_compute_exit(void)
{
	return tcd_exit();
}

module_init(tiny_compute_init);
module_exit(tiny_compute_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Out-of-tree tiny_compute device module");
