#include <linux/printk.h>
#include "common.h"

int mxm_init(void)
{
	pr_info("matx_mock: loaded\n");
	return 0;
}

void mxm_exit(void)
{
	pr_info("matx_mock: unloaded\n");
}
