# README – linux-kernel-driver-sandbox

A sandbox for learning Linux kernel driver development by doing it.
The human writes the kernel and test code. Agent assistance is limited to project setup and review. Otherwise, what's the point?

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
  - builds userspace test applications, shared libraries and Lua scripts; the initramfs carries the loader and libraries they need
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

**The exercises** are the driver work itself. Each exercise is one tree,
`exercises/<name>/`: its own SPEC.md and ARCHITECTURE.md, `driver/` (the
kernel module and its kbuild Makefile) and `userspace/` (the test program
and library, each with a plain Makefile, plus optional `script/` files).
The recipes build and test one exercise at a time, the one named in
`active_exercise.just`.

## Getting started

### Install host tools

```
brew install just podman qemu clang-format
```

### From a fresh clone

```
just machine-vdev
just image-vdev
just kernel-build-vdev   # first run: 10-15 minutes, fetches the kernel tarball
just driver-vdev
just userspace-vdev
just initramfs-vdev
just run-vtarget         # exit with Ctrl-A X
```

### At the vtarget prompt

load and test all drivers:
```
/usr/bin/lkds-test
```
(`just test-vtarget` on the host boots the target, runs it and reports the result; console log in `out/vtarget-test.log`)

individual driver test:
```
insmod /lib/modules/<driver-name>.ko
dmesg
/usr/bin/<test-program-name>
```

### Additional deets

`just format` and `just checkpatch-vdev` apply and check kernel style on
driver sources. `just --list` is the authoritative recipe
list; ARCHITECTURE.md explains what each piece does and how they fit
together.

### Editor setup

Code intelligence for driver and userspace sources comes from clangd
running inside the build container (`just clangd-vdev`), fed by
`out/compile_commands.json`, which `just test` regenerates.
The editor's clangd client is pointed at that recipe in place of the
`clangd` binary, run as `agent-user` because the Podman machine is
theirs:

```
sudo -n -H -u agent-user /opt/homebrew/bin/just --justfile /Users/<your-user>/projects/linux-kernel-driver-sandbox/justfile clangd-vdev
```

That configuration names your account and your checkout path, so it is
local and gitignored. For Zed, create `.zed/settings.json` at the repo
root (the `language_servers` lines keep the Swift extension's
sourcekit-lsp from claiming C files):

```json
{
  "languages": {
    "C": { "language_servers": ["clangd", "!sourcekit-lsp", "..."] },
    "C++": { "language_servers": ["clangd", "!sourcekit-lsp", "..."] }
  },
  "lsp": {
    "clangd": {
      "binary": {
        "path": "/usr/bin/sudo",
        "arguments": ["-n", "-H", "-u", "agent-user", "/opt/homebrew/bin/just",
                      "--justfile", "/Users/<your-user>/projects/linux-kernel-driver-sandbox/justfile",
                      "clangd-vdev"]
      }
    }
  }
}
```

Allow that one command passwordless in sudoers
(`sudo visudo -f /etc/sudoers.d/lkds`):

```
<your-user> ALL=(agent-user) NOPASSWD: /opt/homebrew/bin/just --justfile /Users/<your-user>/projects/linux-kernel-driver-sandbox/justfile clangd-vdev
```

Go-to-definition into kernel headers returns a `/kernel/...` path the
host cannot open; everything within the repo resolves.

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
