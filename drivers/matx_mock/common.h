#pragma once

// lifecycle
extern int mxm_init(void);
extern void mxm_exit(void);

// TBD: only everything.
extern int mxm_probe(void);

#define MXM_VENDOR_ID 0x1234
#define MXM_DEVICE_ID 0x11e8
