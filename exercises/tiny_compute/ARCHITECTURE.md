# ARCHITECTURE – tiny_compute

## Project Layout

### Driver Impl – exercises/tiny_compute/driver

- common.h: device constants (macros and enums), structs, function prototypes
- main.c: entry point
- init_exit.c: driver life cycle
- probe_remove.c: device instance life cycle
- fops.c: file descriptor management and ioctl dispatcher (ABI)
- dma.c: DMA operations implementation
- irq.c: interrupt handler for compute and DMA operations
- tcd_ioctl.h: userspace-facing ABI header
- Makefile: kbuild format makefile fragment

### Userspace – exercises/tiny_compute/userspace

The API definition, then three consumers of the driver, each one layer up from the last:

- api_def/: the userspace API defined once, generated into every consumer
  - tcdl_api.adef.toml: types, constants, functions and docstrings of the `tcdl` API, plus the pins tying its constants to `tcd_ioctl.h`
- lib/: `libtiny_compute.so`, the C wrapper library over the ioctl ABI
  - tcdl_api.cpp: implementation of the generated `tcdl_api.h` (namespace `tcdl_`/`TCDL_`, the foreign-function surface); the opaque handle wraps the device fd
  - util.h: internal helpers
  - Makefile: `LINK_TYPE := SO` plus `../../../cpp.mk`
- app/: `tiny_compute`, the C++ test program, linked against the library
  - common.h: utility definitions and function prototypes
  - main.cpp: entry point
  - tests.cpp: functionality tests through the generated C++ wrapper `tcdl_api.hpp`
  - Makefile: `LINK_TYPE := EXE` plus `../../../cpp.mk`
- script/: LuaJIT scripts, staged as-is and run as tests
  - test_tcdl.lua: the tests, written against the generated module `binding/tcdl_api.lua`, which is staged beside the scripts and binds `libtiny_compute.so` through the FFI

## Project Design

### Driver

- professional standards - strict kernel formatting with checkpatch validation, no circumvention thereof
  - namespacing convention for all structs, functions, etc is `tcd_` and `TCD_`
- separation of concerns by translation units to keep each implementation file comprehensible
- multi-thread safe
  - mutex guards around interrupt-gated operations
  - completion per interrupt-gated operation
- multi-device capable
  - every piece of state lives in the per-device `tcd_dev`; the only shared object is the driver-wide IDA that numbers instances
  - each instance registers `/dev/tiny_compute<N>` with an IDA-allocated `N` and a `devm_kasprintf` name; `remove` releases the number after the node is gone so it can be reused
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
    - bidirectional DMA - interrupt-gated sync RW ops through the device's 4 KiB buffer; the driver stages through coherent buffers and userspace never sees a bus address

### Library

- designed as a foreign-function surface first: opaque handle, fixed-width arguments, enum results with explicit values, no callbacks, no varargs
- the header is for C and C++ consumers; the Lua module does not read it. The module gets its FFI declarations from the generator's cdef rendering of the structs and functions and its constants from the definition's model, so the header's untyped constants are macros typed by their group's `_base_type` (`UINT32_C` for the capability flags) and its enums are the typed groups (`tcdl_result`)
- the handle is the device fd xored with a constant cast to a pointer, so the library carries no state of its own and a handle costs nothing to copy
- error mapping is one direction: errno from the ioctl to a `tcdl_result`; the caller never sees errno. `-EOPNOTSUPP` from a capability gate maps to `TCDL_ERR_UNSUPPORTED`
- the definition is the source of truth. `api_def/tcdl_api.adef.toml` states the API once; the C header (with the ABI pins in its implementation-only block), the header-only C++ wrapper, the Lua module and the implementation stub are generated from it by the framework's `vdev/api_gen/` (root ARCHITECTURE.md "API generation"). `lib/tcdl_api.cpp` is the one hand-written piece and follows the generated header
- device capabilities live in the driver's per-device state and gate the operations; `tcdl_info.device_caps` reports them, and the composed masks (`TCDL_CAP_DMA_READ_WRITE`, `TCDL_CAP_ALL`) exist only on the library side, since convenience is not the ABI header's job

### Driver Test

- the C++ program and the Lua script both go through the library; nothing in userspace issues an ioctl except `tcdl_api.cpp`
- exercise every ABI function
  - acquisition, info, liveness, compute, DMA round trip (pattern out and back through the device buffer, compared byte for byte)
- two homes, split by what each language can do
  - the C++ program: the smoke test through the library, and the one threaded case, two threads on one fd (**NYI**)
  - the Lua script: **IN PROGRESS** everything multi-device and multi-process, since Lua has no threads and coroutines are cooperative; N processes across all devices, the isolation check, and the adversarial phase
- isolate testing into two phases
  - 'walk right down Main Street' (what's being done now)
  - **NYI**: 'be mean and nasty' aka adversarial usage patterns (coming soon to a horror show near you)

## Roadmap

The stack from driver to script, one host coordinating several accelerators through a library and a binding, is in place. Remaining, in order:

- DONE 2026-09-25: the generator's test suite restructured; compiled and executed checks against a fake library in the container, text assertions replaced by properties from the model, files split by output.
- DONE 2026-09-25: the API generator's emitters, C header with ABI pins, Lua module, header-only C++ wrapper and implementation stub; the test program runs on the wrapper and the Lua test on the module.
- The torture suite in Lua against the binding, multi-process, across the two instances the test machine boots: the isolation check (a DMA pattern written to one device must not be readable from the other, and operations on the two must not serialise on each other), then `open`/`release` under contention and the per-device locks. The driver side is done. The C++ program shrinks to a smoke test through the library plus its one threaded case.
- proper dmsg logging
- A Rust port of the driver.
- Driver-side device mocking to present additional design considerations to ABI and surfaces to userspace.
  - will build on existing IRQ and DMA mechanisms
  - computation will be mocked and placed into device buffer, user will have to fetch them via normal mechanism
  - will blend device handling logic in the driver with more sophisticated 'compute device' ABI offered to userland 
- Removal while open: `misc_deregister` does not close open files, so an ioctl can run after `remove` (reachable via sysfs `unbind`). A removed flag in `tcd_dev`, set in `remove` under the operation locks and checked by every ioctl (`-ENODEV`), plus the adversarial test that exercises it.
