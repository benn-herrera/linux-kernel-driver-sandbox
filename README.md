# README – linux-kernel-driver-sandbox

A sandbox for learning Linux kernel driver development by doing the it.
The human writes the kernel code. Agent assistance is limited to project setup and review. Otherwise, what's the point?

## Platform

### Host

This project is set up for macOS on Apple Silicon and makes no pretensions to portability.
That said, this is a *Linux* kernel driver sandbox. If one was developing on Linux directly 
the Podman virtualized dev machine would be unnecessary, and the pieces here could fairly easily
be re-arranged to work.

### Virtualized Machines

- vdev: Podman-run virtual Debian Linux ARM64 dev machine
  - image defined by `./Containerfile`
  - builds a Debian kernel with Rust enabled (once)
  - builds driver projects (C and/or Rust)
  - builds userspace test applications (any project that builds a statically linked executable)
- vtarget: QEMU-run virtual ARM64 test target
  - boots the Debian image built by vdev (`./out/Image`), minimal ramfs/busybox setup
  - drivers and userspace programs built on vdev are available following boot

## Two layers

**The framework** is the runner and everything it drives: the root
`justfile` (host recipes), `vdev/justfile` (kernel and driver recipes, run
inside the build container), the `Containerfile`, the Podman dev box, the
kernel build, the initramfs, and the QEMU boot. It is owned by the project
documents at the repo root — THESIS.md, ARCHITECTURE.md, CONVENTIONS.md —
which describe it in full.

**The exercises** are the driver work itself. Each exercise is a triplet:
`exercises/<name>/` holds the exercise's own SPEC.md and ARCHITECTURE.md,
`drivers/<name>/` holds the kernel module and its kbuild Makefile, and
`userspace/<name>/` holds a static test program with a plain Makefile.

## Getting started

Install host tools:

```
brew install just podman qemu clang-format
```

From a fresh clone:

```
just machine-vdev
just image-vdev
just kernel-build-vdev   # first run: 10-15 minutes, fetches the kernel tarball
just modules-vdev
just userspace-vdev
just initramfs-vdev
just run-vtarget         # exit with Ctrl-A X
```

At the vtarget prompt:

```
insmod /lib/modules/<driver-name>.ko
dmesg
/usr/bin/<test-program-name>
```

`just format` and `just checkpatch-vdev` apply and check kernel style on
driver and userspace sources. `just --list` is the authoritative recipe
list; ARCHITECTURE.md explains what each piece does and how they fit
together.

## Documents

THESIS.md states the intent behind the project, ARCHITECTURE.md describes
how this implementation is built, and CONVENTIONS.md holds the project's
rules — naming, where each recipe executes, the read-only mounts, and style.
Each exercise directory carries its own SPEC.md and ARCHITECTURE.md.

## Third Party Acknowledgements

- **just** — Casey Rodarmor — CC0-1.0 — task runner for both justfiles.
- **Podman** — Red Hat / containers project — Apache-2.0 — build-host
  virtual machine and container runtime.
- **QEMU** — QEMU project — GPL-2.0 (with component-level exceptions) —
  boots the kernel image under `qemu-system-aarch64`; also the source of the
  `edu` stand-in device.
- **LLVM/clang, lld, clang-format** — LLVM project — Apache-2.0 with LLVM
  exception — kernel toolchain (`LLVM=1` build) and source formatting.
- **Rust, rustfmt, rust-clippy** — Rust project — MIT/Apache-2.0 — kernel
  Rust support toolchain.
- **bindgen** — Rust project — BSD-3-Clause — Rust-to-C binding generation
  for the kernel build.
- **BusyBox** — Denys Vlasenko and contributors — GPL-2.0 — provides the
  vtarget shell and utilities via the static initramfs.
- **Debian** (`debian:trixie-slim`) — Debian project — various (Debian
  licensing) — base image for the build container.
