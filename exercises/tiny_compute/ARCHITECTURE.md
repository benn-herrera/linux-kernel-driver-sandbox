# ARCHITECTURE – tiny_compute

## Project Layout

### Driver Impl – drivers/tiny_compute

- common.h: device constants (macros and enums), structs, function prototypes
- main.c: entry point
- init_exit.c: driver life cycle
- probe_remove.c: device instance life cycle
- fops.c: file descriptor management and ioctl dispatcher (ABI)
- dma.c: DMA operations implementation
- irq.c: interrupt handler for compute and DMA operations
- tcd_ioctl.h: userspace-facing ABI header
- Makefile: kbuild format makefile fragment

### Driver Test – userspace/tiny_compute

- common.h: utility definitions and function prototypes for test program
- main.cpp: entry point for test program that exercises the tiny_compute driver ABI
- functionality.cpp: basic functionality tests (does it do the thing?)
- resilience.cpp: adversarial usage tests (does it blow up if you kick it?)
- Makefile: single line consumer of `../cpp.mk`, generic C++ userspace project Makefile

## Project Design

### Driver

- professional standards - strict kernel formatting with checkpatch validation, no circumvention thereof
  - namespacing convention for all structs, functions, etc is `tcd_` and `TCD_`
- separation of concerns by translation units to keep each implementation file comprehensible
- multi-thread safe
  - mutex guards around interrupt-gated operations
  - completion per interrupt-gated operation
- multi-device capable
  - **NYI**: name allocation and release 
- resilient, with full error trapping for all potential failure modes
- reasonable userspace ABI
  - balances driver thinness with standard userspace functionality and responsibility expectations
  - synchronous interrupt-driven operations
  - TBD: asynchronous interrupt-driven operations? current lean is that's a userspace concern.
  - implemented:
    - open/close (fops)
    - info - simple sync RO op
    - liveness - simple sync RW op
    - compute - interrupt-gated sync RW op 
  - **NYI**:
    - bidirectional DMA - interrupt-gated sync RW ops

### Driver Test

- exercise every ABI function
  - acquisition, info, liveness, compute
  - **NYI**: DMA, multi-threaded access 
- single and multi-device scenarios
- single and multi-threaded usage patterns
- isolate testing into two phases
  - 'walk right down Main Street' (what's being done now)
  - **NYI**: 'be mean and nasty' aka adversarial usage patterns (coming soon to a horror show near you)

## Roadmap

- DMA through the edu device.
- A multi-threaded test program exercising the per-device locks.
- Multiple device instances with per-instance device nodes.
- A C wrapper library over the ioctl ABI (`userspace/libtcd/`), consumed by
  the test program and shaped for foreign-function binding.
- A LuaJIT binding to that library through its FFI, running in the guest
  (needs the dynamic-library initramfs tier; see the root ARCHITECTURE.md).
- proper dmsg logging
- A Rust port of the driver.
- Driver-side device mocking to present additional design considerations to ABI and surfaces to userspace.
  - will build on existing IRQ and DMA mechanisms
  - computation will be mocked and placed into device buffer, user will have to fetch them via normal mechanism
  - will blend device handling logic in the driver with more sophisticated 'compute device' ABI offered to userland 
- Removal while open: `misc_deregister` does not close open files, so an
  ioctl can run after `remove` (reachable via sysfs `unbind`). A removed
  flag in `tcd_dev`, set in `remove` under the operation locks and checked
  by every ioctl (`-ENODEV`), plus the adversarial test that exercises it.

### DMA Burndown

1. **DONE** The safety net first. A second fragment, vdev/kernel-config/dma_api_debug.config, with CONFIG_DMA_API_DEBUG=y, then just
kernel-config-vdev and just kernel-build-vdev. That option makes the kernel track every DMA mapping and report misuse in dmesg: a buffer
freed while mapped, an unmap with the wrong size, a device that never unmapped at unload. It changes headers, so expect a longer rebuild
than usual.

2. Buffers in probe. dmam_alloc_coherent(&pdev->dev, TCD_DMA_BUF_SIZE, &tcd->dma_handle, GFP_KERNEL) gives two addresses for one page: a
CPU pointer for the driver to read and write, and a dma_addr_t for the device. Coherent means no cache maintenance calls; the managed form
frees it on remove in the right order, after the IRQ if the IRQ is freed manually in remove, which it is. One page matches the device's 4 KiB buffer at 0x40000. Two buffers, one per direction, keep the round trip honest.

3. The transfer in dma.c. Under dma_lock: reinit_completion(&tcd->dma_done); write source, destination and count; write the command
register with START | RAISE, plus DIRECTION for device to host; wait on dma_done with a timeout. The DMA registers are 64-bit, so use
iowrite64 with linux/io-64-nonatomic-lo-hi.h included, which is the portable spelling. Host to device: source is the dma_addr_t,
destination 0x40000. Device to host: source 0x40000, destination the other buffer's dma_addr_t. Edu completes a transfer on a QEMU timer,
so the wait is real, tens of milliseconds.

4. The ABI. Two operation-shaped ioctls matching your dma.c prototypes: TCD_IOC_DMA_WRITE takes a user buffer and a length, copy_from_user
into the coherent buffer, transfer to the device; TCD_IOC_DMA_READ transfers from the device into the other buffer and copy_to_user. Length
validated against the page size before anything else, since it is unbounded userspace input. The device address never appears in the ABI.

5. The test. Write a pattern, read it back, compare. Then dmesg clean of DMA-API lines, which is what step 1 was for.
