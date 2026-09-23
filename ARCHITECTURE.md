# ARCHITECTURE – linux-kernel-driver-sandbox

> Describes the implementation as built. `just --list` is the authoritative
> list of recipes; a recipe named here that is not listed there is a
> documentation defect.

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
  `kernel-build-vdev`, `kernel-clean-vdev`, `modules-vdev`,
  `modules-clean-vdev`, `userspace-vdev`, `userspace-clean-vdev`,
  `initramfs-vdev`, `checkpatch-vdev`, `format-vdev`) depend on
  `machine-vdev` and compose one line: `just run-vdev just --justfile
  /work/vdev/justfile <name>`, where `<name>` is the root recipe's name
  with the `-vdev` suffix removed; `checkpatch-vdev` and `format-vdev`
  pass their arguments through. The recipe dependency chain (build needs
  config needs fetch) lives in `vdev/justfile`, so one container run
  covers a workflow.
- Neither justfile carries staleness logic of its own.
- Staleness ownership is split by target: kbuild owns kernel and module
  staleness; the podman build owns image layer caching; the
  `machine-vdev` target checks live state (`podman machine inspect`), not
  timestamps.
- The project's Makefiles are the kbuild Makefiles under `drivers/<name>/`,
  needed for out-of-tree module builds (`make M=...`) and invoked from the
  `modules` recipe in `vdev/justfile`, and the plain Makefiles under
  `userspace/<name>/` invoked from its `userspace` recipe (see "Userspace
  programs").

## Build host: Podman machine

- Apple Virtualization provider, the account default machine. See
  CONVENTIONS.md for ownership.
- Created and started by `just machine-vdev`; sized by the `MACHINE_CPUS`,
  `MACHINE_MEMORY_MIB`, `MACHINE_DISK_GB` justfile variables. Changing a
  size variable does not resize an existing machine (CONVENTIONS.md).

## Build environment: container image

- A Containerfile in the repo root defines the kernel toolchain: clang/LLVM
  19 with lld, driven with `LLVM=1` on every kbuild invocation because the
  kernel's Rust support builds with LLVM; Rust 1.85 (`rustc`, `rust-src`,
  `rustfmt`, `rust-clippy`) and bindgen 0.71 from trixie; GNU make, flex,
  bison, bc, libssl-dev, libelf-dev, libncurses-dev, python3, cpio, kmod,
  rsync, curl, busybox-static, gdb, pahole (dwarves), sparse, the
  xz/zstd/lz4 compressors, `clang-format` (same major as clang), and
  `just` (runs `vdev/justfile`).
  `build-essential` remains in the image (GNU make, libc headers); with
  `LLVM=1` kbuild uses clang for both target and host objects.
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
- Four host directories are bind-mounted: `drivers/` read-only at
  `/work/drivers` (driver source), `userspace/` read-only at
  `/work/userspace` (userspace program source), `OUT_DIR` (`out/`) at
  `/work/out` (the only writable mount: build output handed to the host),
  and `vdev/` read-only at `/work/vdev` (the in-container justfile).
  `just run-vdev` and `just shell-vdev` create the first three on the host
  before mounting; the mount set is the `MOUNTS` variable in the root
  justfile.

## Kernel source and build

- Source is the stable release tarball pinned by `KERNEL_VERSION` in
  `vdev/justfile`, fetched from kernel.org by `just kernel-fetch-vdev`,
  verified against the release directory's `sha256sums.asc`, and extracted
  to `KERNEL_SRC` (`/kernel/linux-<version>`) in the volume. Present tree
  means no fetch.
- The build is in-tree (no `O=`) with clang: every make invocation in
  `vdev/justfile` goes through its `MAKE` variable (`make LLVM=1`).
  `just kernel-config-vdev` runs `make defconfig debug.config` in
  `KERNEL_SRC`, merges the project fragments (see "Test kernel
  configuration") and fails unless `CONFIG_RUST` ends up `y`;
  `just kernel-build-vdev` builds the `Image` and `modules` targets and
  copies `Image` to `out/`. The `modules` target is what produces
  `Module.symvers`, which out-of-tree builds need. `just kernel-clean-vdev`
  is `make clean`, keeping `.config`.

## Test kernel configuration

- defconfig plus the kernel's `debug.config` fragment: KASAN, UBSAN,
  kmemleak, DEBUG_OBJECTS, lockdep (PROVE_LOCKING, DEBUG_ATOMIC_SLEEP).
- The project's own fragments under `vdev/kernel-config/*.config`, merged
  on top by `scripts/kconfig/merge_config.sh -m` then `make olddefconfig`.
  `rust.config` sets `CONFIG_RUST=y`. Kconfig drops `CONFIG_RUST=y`
  silently when the toolchain check fails, so `kernel-config` verifies it
  with `scripts/config --state RUST`.
- DMA_API_DEBUG added where a driver maps DMA.

## Boot

- `just run-vtarget` runs host QEMU (`qemu-system-aarch64`): machine type
  `virt`, `-accel hvf`, `-cpu host`; CPUs and memory from the `VTARGET_CPUS`
  and `VTARGET_MEMORY` justfile variables.
- Devices come from the `VTARGET_DEVICES` justfile variable, a space-separated
  list of QEMU device names added as `-device <name>`; default `edu`, QEMU's
  educational PCI device (vendor `0x1234`, device `0x11e8`, documented at
  `docs/specs/edu.rst` in the QEMU tree). `just VTARGET_DEVICES="" run-vtarget`
  boots with no device.
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
  kernel and module recipes.
- If `out/modules/` exists, every `.ko` in it is staged at `/lib/modules/`;
  otherwise the archive is built without modules and says so on stderr.
- If `out/userspace/` exists, every file in it is staged executable at
  `/usr/bin/`; otherwise the archive is built without userspace programs
  and says so on stderr.

## Debugging

- QEMU exposes its gdbstub on a host port.
- gdb runs inside the build container, next to the `vmlinux` in the build
  volume, and connects to the host port. How the container reaches that
  host port is not yet verified.

## Driver code

- One module per directory: `drivers/<name>/` holds the sources and a
  kbuild `Makefile` (`obj-m += <name>.o`). The kernel tree path and `M=`
  come from the recipe, not the Makefile.
- `just modules-vdev` runs `make -C KERNEL_SRC M=/work/drivers/<name>
  MO=/work/out/modules-build/<name> modules` for every `drivers/*/` with a
  `Makefile`, against the in-tree build in the volume; it fails naming
  `kernel-build` if `Module.symvers` is absent. `MO=` sends every kbuild
  artifact to the output tree, so `drivers/` is never written and is
  mounted read-only. The resulting `.ko` files are copied to `out/modules/`
  (stale `.ko` files cleared first). `just modules-clean-vdev` removes
  `out/modules-build/` and `out/modules/`.
- `just initramfs-vdev` places the `.ko` files at `/lib/modules/` in the
  guest; load with `insmod /lib/modules/<name>.ko`, unload with `rmmod`.
  Modules are built for this kernel tree only, with no version
  compatibility shims.

## Userspace programs

- One program per directory: `userspace/<name>/` holds the sources and a
  plain GNU Makefile (not kbuild) that honours `CC` and `OUT`, writes only
  under `OUT`, and links `-static`: the guest has no shared libraries.
- `just userspace-vdev` runs `make -C /work/userspace/<name> CC=clang
  CXX=clang++ OUT=/work/out/userspace-build/<name>
  DRIVER_INCLUDE=/work/drivers` for every `userspace/*/` with a
  `Makefile`, then copies the product `<name>` from that tree to
  `out/userspace/`, which holds only what the initramfs ships (cleared
  first). It does not depend on the kernel recipes.
  `just userspace-clean-vdev` removes `out/userspace-build/` and
  `out/userspace/`.
- `just initramfs-vdev` places the binaries at `/usr/bin/` in the guest,
  which is on busybox's default `PATH`. `userspace/matx_mock/` is the
  first test exercise.

## Style tools

- `just checkpatch-vdev [name]` runs the kernel tree's
  `scripts/checkpatch.pl --no-tree --terse -f` over every `*.c` and `*.h`
  under `drivers/*/`, or under `drivers/<name>/` only. Its exit status is
  checkpatch's own: nonzero on any error or warning. It fails naming
  `kernel-fetch` when the tree is absent.
- `just format` runs on the host: the Homebrew `clang-format` with the
  kernel tree's `.clang-format`, exported to `out/clang-format` by
  `just export-clang-format-vdev` (a prerequisite, no-op once present),
  over every `*.c` and `*.h` under `drivers/` and `userspace/`, so both
  sides of an exercise share kernel style. It rewrites files in place. It
  runs on the host because a rewrite from inside the container replaces
  the file with root's umask and drops the group-write bit the IDE needs.

## Repo layout

- `justfile`, `vdev/justfile`, `vdev/initramfs/` and `vdev/kernel-config/`
  (mounted at `/work/vdev`), `Containerfile`, the project documents,
  `drivers/` (mounted at `/work/drivers`; `drivers/matx_mock/` is the first
  user exercise driver), `userspace/` (mounted at
  `/work/userspace`; `userspace/matx_mock/` is the driver test), `out/`
  (gitignored build output, mounted at `/work/out`), `.claude-temp/`
  (gitignored scratch).

## Explicitly out of scope

- virtme-ng, and booting inside the Podman machine: either would require
  nested virtualization. The boot runs on the host.
