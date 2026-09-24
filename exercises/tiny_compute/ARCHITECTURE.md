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
  - every piece of state lives in the per-device `tcd_dev`; the only shared
    object is the driver-wide IDA that numbers instances
  - each instance registers `/dev/tiny_compute<N>` with an IDA-allocated
    `N` and a `devm_kasprintf` name; `remove` releases the number after the
    node is gone so it can be reused
  - the test machine boots two `edu` instances so both paths run every time
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
    - bidirectional DMA - interrupt-gated sync RW ops through the device's
      4 KiB buffer; the driver stages through coherent buffers and userspace
      never sees a bus address

### Driver Test

- exercise every ABI function
  - acquisition, info, liveness, compute, DMA round trip (pattern out and
    back through the device buffer, compared byte for byte)
  - **NYI**: multi-threaded access
- single and multi-device scenarios
- single and multi-threaded usage patterns
- isolate testing into two phases
  - 'walk right down Main Street' (what's being done now)
  - **NYI**: 'be mean and nasty' aka adversarial usage patterns (coming soon to a horror show near you)

## Roadmap

The stack from driver to script is the priority: one host coordinating
several accelerators through a library and a binding. In order:

- Multi-device isolation check in the test program: a DMA pattern written
  to one device must not be readable from the other, and operations on the
  two must not serialise on each other. The driver side is done; the test
  expects the two instances the test machine boots.
- A C wrapper library over the ioctl ABI (`userspace/libtcd/`), designed as
  the foreign-function surface: opaque handle, fixed-width arguments,
  errno-style results, no callbacks. Built as a shared object for the
  binding and an archive for the static C++ program, which shrinks to a
  smoke test through the library.
- The dynamic-library initramfs tier (see the root ARCHITECTURE.md) with
  LuaJIT from the build image, and a LuaJIT FFI binding to `libtcd`.
- The torture suite in Lua against the binding: multi-process, since Lua
  has no threads and coroutines are cooperative, N processes across all
  devices, exercising `open`/`release` under contention and the
  per-device locks. The one threaded case, two threads on one fd, stays in
  the C++ program.
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
