# ARCHITECTURE – linux-kernel-driver-sandbox

> Draft. Describes the intended implementation ahead of the code. Targets
> that exist so far: `just host-check`, `just machine-vdev`,
> `just machine-stop-vdev`, `just image-vdev`, `just run-vdev`,
> `just shell-vdev`, `just kernel-fetch-vdev`, `just kernel-config-vdev`,
> `just kernel-build-vdev`, `just kernel-clean-vdev`, `just initramfs-vdev`,
> `just run-vtarget`.

Consumer-facing outcomes belong to SPEC.md; this document covers how this
implementation meets them. Podman-machine ownership and the Homebrew
install-failure contract are defined in CONVENTIONS.md and are cited, not
restated, below.

## Host

- macOS on Apple Silicon (M3).
- Tools from Homebrew: `just` (runner), `podman` (build host), `qemu`
  (boot). See CONVENTIONS.md for the install-failure contract.

## Runner (`just`)

- Two justfiles, each executing where it is mounted (CONVENTIONS.md). The
  root `justfile` runs on the macOS host: machine lifecycle, image build,
  the container bridge, and the workflow entry points. `vdev/justfile` is
  bind-mounted read-only at `/work/vdev` and run by the `just` in the image;
  it holds the kernel recipes and the `KERNEL_VERSION` pin.
- `just run-vdev <cmd>` is the single bridge into the container: it fails
  with `dev box is not running: run 'just machine-vdev'` unless the machine
  is already running, then runs `<cmd>` in a fresh container with the
  `MOUNTS` set. It never starts the machine.
- Root workflow recipes (`kernel-fetch-vdev`, `kernel-config-vdev`,
  `kernel-build-vdev`, `kernel-clean-vdev`) depend on `machine-vdev` and
  compose one line: `just run-vdev just --justfile /work/vdev/justfile
  <name>`, where `<name>` is the root recipe's name with the `-vdev`
  suffix removed. The recipe dependency chain (build needs config needs
  fetch) lives in `vdev/justfile`, so one container run covers a workflow.
- Neither justfile carries staleness logic of its own.
- Staleness ownership is split by target: kbuild owns kernel and module
  staleness; the podman build owns image layer caching; the
  `machine-vdev` target checks live state (`podman machine inspect`), not
  timestamps.
- The project's only Makefile is the kbuild Makefile under `drivers/`,
  needed for out-of-tree module builds (`make M=...`), invoked from a just
  recipe.

## Build host: Podman machine

- Apple Virtualization provider, the account default machine. See
  CONVENTIONS.md for ownership.
- Created and started by `just machine-vdev`; sized by the `MACHINE_CPUS`,
  `MACHINE_MEMORY_MIB`, `MACHINE_DISK_GB` justfile variables. Changing a
  size variable does not resize an existing machine (CONVENTIONS.md).

## Build environment: container image

- A Containerfile in the repo root defines the kernel toolchain: gcc, GNU
  make, flex, bison, bc, libssl-dev, libelf-dev, libncurses-dev, python3,
  cpio, kmod, rsync, curl, busybox-static, gdb, pahole (dwarves), sparse,
  the xz/zstd/lz4 compressors, and `just` (runs `vdev/justfile`).
- Base image: `docker.io/library/debian:trixie-slim`. Built by
  `just image-vdev` as `IMAGE` (`lkds-build`) from the Containerfile on
  stdin, with no build context.
- Processes in the container run as root. Under rootless Podman that is the
  machine-side account, so bind-mounted files land owned by the host user.
- The target is ARM64: the guest runs near-native under HVF on the Apple
  Silicon host. An x86_64 cross-gcc is added when that platform comes into
  scope.
- Image and volume names carry the project prefix `lkds-`.

## Storage

- Kernel source and build output live in Podman volumes, never on a host
  bind mount: host directories reach the machine over virtiofs, and a
  kernel build across that boundary is several times slower than on a
  volume.
- The named volume `KERNEL_VOLUME` (`lkds-kernel`) is mounted at `/kernel`,
  the container's working directory. Podman creates it on first use.
- Three host directories are bind-mounted: `drivers/` at `/work/drivers`
  (driver source), `OUT_DIR` (`out/`) at `/work/out` (build output handed
  to the host), and `vdev/` read-only at `/work/vdev` (the in-container
  justfile). `just run-vdev` and `just shell-vdev` create the first two on
  the host before mounting; the mount set is the `MOUNTS` variable in the
  root justfile.

## Kernel source and build

- Source is the stable release tarball pinned by `KERNEL_VERSION` in
  `vdev/justfile`, fetched from kernel.org by `just kernel-fetch-vdev`,
  verified against the release directory's `sha256sums.asc`, and extracted
  to `KERNEL_SRC` (`/kernel/linux-<version>`) in the volume. Present tree
  means no fetch.
- The build is in-tree (no `O=`): `just kernel-config-vdev` runs
  `make defconfig debug.config` in `KERNEL_SRC`; `just kernel-build-vdev`
  builds `Image` and copies it to `out/`. `just kernel-clean-vdev` is
  `make clean`, keeping `.config`.
- Modules are not yet built.

## Test kernel configuration

- defconfig plus the kernel's `debug.config` fragment: KASAN, UBSAN,
  kmemleak, DEBUG_OBJECTS, lockdep (PROVE_LOCKING, DEBUG_ATOMIC_SLEEP).
- DMA_API_DEBUG added where a driver maps DMA.

## Boot

- `just run-vtarget` runs host QEMU (`qemu-system-aarch64`): machine type
  `virt`, `-accel hvf`, `-cpu host`; CPUs and memory from the `VTARGET_CPUS`
  and `VTARGET_MEMORY` justfile variables.
- Headless (`-nographic`): the guest's serial console `ttyAMA0` is the
  terminal; `Ctrl-A X` exits. `earlycon` on the kernel command line.
- `panic=1` on the command line with `-no-reboot`: a kernel panic ends the
  QEMU process instead of hanging or rebooting.
- Inputs: `out/Image` and `out/initramfs.cpio.gz`, both produced in the
  container. The recipe fails naming the producing recipe when either is
  absent. No networking flags yet; QEMU's default applies.
- x86_64, later, boots the same way under TCG emulation with no
  acceleration.

### Initramfs

- `vdev/initramfs/init`, a POSIX sh script: mounts proc, sysfs and devtmpfs,
  prints the marker `lkds: userspace reached` and `uname -r`, then
  `exec setsid cttyhack sh` for a shell with job control on the console.
- `just initramfs-vdev` stages `/bin/busybox` (the image's `busybox-static`,
  checked static with `file`), `/init`, the applet symlinks (installed under
  `chroot` so they target `/bin/busybox`) and the `bin`, `sbin`, `proc`,
  `sys`, `dev` directories in a container temp dir, then packs a gzipped
  newc cpio to `out/initramfs.cpio.gz`. Always rebuilds; independent of the
  kernel recipes.

## Debugging

- QEMU exposes its gdbstub on a host port.
- gdb runs inside the build container, next to the `vmlinux` in the build
  volume, and connects to the host port. How the container reaches that
  host port is not yet verified.

## Driver code

- Out-of-tree modules live under `drivers/` in the repo.
- Built with `make M=...` against the kernel build tree in the volume.
- Loaded in the booted guest via the initramfs.

## Repo layout

- `justfile`, `vdev/justfile` and `vdev/initramfs/` (mounted at
  `/work/vdev`), `Containerfile`, the project documents,
  `drivers/` (mounted at `/work/drivers`), `out/` (gitignored build output,
  mounted at `/work/out`), `.claude-temp/` (gitignored scratch).

## Explicitly out of scope

- virtme-ng, and booting inside the Podman machine: either would require
  nested virtualization. The boot runs on the host.
