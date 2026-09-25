// SPDX-License-Identifier: GPL-2.0
/*
 * init_exit:  driver life cycle
 */
#include "common.h"
#include <linux/init.h>
#include <linux/printk.h>

static const struct pci_device_id tcd_ids[] = { { PCI_DEVICE(TCD_VENDOR_ID,
							     TCD_DEVICE_ID) },
						{} };
MODULE_DEVICE_TABLE(pci, tcd_ids);

static struct pci_driver tcd_driver = {
	.name = TCD_NAME,
	.id_table = tcd_ids,
	.probe = tcd_probe,
	.remove = tcd_remove,
	.shutdown = NULL,
};

int tcd_init(void)
{
	int result = pci_register_driver(&tcd_driver);

	pr_info(pr_fmt("%s\n"),
		result == 0 ? "registered." : "REGISTRATION FAILED!");
	return result;
}

void tcd_exit(void)
{
	pci_unregister_driver(&tcd_driver);
	pr_info(pr_fmt("unloaded.\n"));
}
