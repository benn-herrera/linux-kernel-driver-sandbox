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

- tiny_compute.cpp: test program that exercises the tiny_compute driver ABI
- Makefile: userspace project C/C++ makefile (100% generic and copyable)

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
- A Rust port of the driver.
- A C wrapper library over the ioctl ABI (`userspace/libtcd/`), consumed by
  the test program and shaped for foreign-function binding.
- A LuaJIT binding to that library through its FFI, running in the guest
  (needs the dynamic-library initramfs tier; see the root ARCHITECTURE.md).
- A custom QEMU device model as a possible later exercise.
