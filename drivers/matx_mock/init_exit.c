// SPDX-License-Identifier: GPL-2.0
#include "common.h"
#include <linux/init.h>
#include <linux/printk.h>

static const struct pci_device_id mxm_ids[] = { { PCI_DEVICE(MXM_VENDOR_ID,
							     MXM_DEVICE_ID) },
						{} };
MODULE_DEVICE_TABLE(pci, mxm_ids);

static struct pci_driver mxm_driver = {
	.name = "matx_mock",
	.id_table = mxm_ids,
	.probe = mxm_probe,
	.remove = mxm_remove,
	.shutdown = NULL,
};

int mxm_init(void)
{
	int result = pci_register_driver(&mxm_driver);

	pr_info("%s\n", result == 0 ? "matx_mock: registered." :
				      "matx_mock: REGISTRATION FAILED!");
	return result;
}

void mxm_exit(void)
{
	pci_unregister_driver(&mxm_driver);
	pr_info("matx_mock: unloaded.\n");
}
