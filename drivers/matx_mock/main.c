// SPDX-License-Identifier: GPL-2.0
/*
 * main: matx_mock driver entry point source file
 */
#include "common.h"
#include <linux/module.h>

static int __init matx_mock_init(void)
{
	return mxm_init();
}

static void __exit matx_mock_exit(void)
{
	return mxm_exit();
}

module_init(matx_mock_init);
module_exit(matx_mock_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Out-of-tree matx_mock device module");
