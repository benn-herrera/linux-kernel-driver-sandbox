# ARCHITECTURE – linux-kernel-driver-sandbox

> Draft. Describes the intended implementation ahead of the code. Targets
> that exist so far: `just host-check`, `just machine`, `just machine-stop`,
> `just image`, `just run`, `just shell`.

Consumer-facing outcomes belong to SPEC.md; this document covers how this
implementation meets them. Podman-machine ownership and the Homebrew
install-failure contract are defined in CONVENTIONS.md and are cited, not
restated, below.

## Host

- macOS on Apple Silicon (M3).
- Tools from Homebrew: `just` (runner), `podman` (build host), `qemu`
  (boot). See CONVENTIONS.md for the install-failure contract.

## Runner (`just`)

- The justfile is a recipe phonebook. It carries no dependency or staleness
  logic of its own.
- Staleness ownership is split by target: kbuild owns kernel and module
  staleness; the podman build owns image layer caching; the `machine`
  target checks live state (`podman machine inspect`), not timestamps.
- The project's only Makefile is the kbuild Makefile under `drivers/`,
  needed for out-of-tree module builds (`make M=...`), invoked from a just
  recipe.

## Build host: Podman machine

- Apple Virtualization provider, the account default machine. See
  CONVENTIONS.md for ownership.
- Created and started by `just machine`; sized by the `MACHINE_CPUS`,
  `MACHINE_MEMORY_MIB`, `MACHINE_DISK_GB` justfile variables. Changing a
  size variable does not resize an existing machine (CONVENTIONS.md).

## Build environment: container image

- A Containerfile in the repo root defines the kernel toolchain: gcc, GNU
  make, flex, bison, bc, libssl-dev, libelf-dev, libncurses-dev, python3,
  cpio, kmod, rsync, busybox-static, gdb, pahole (dwarves), sparse, and the
  xz/zstd/lz4 compressors.
- Base image: `docker.io/library/debian:trixie-slim`. Built by `just image`
  as `IMAGE` (`lkds-build`) from the Containerfile on stdin, with no build
  context.
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
- Two host directories are bind-mounted: `drivers/` at `/work/drivers`
  (driver source) and `OUT_DIR` (`out/`) at `/work/out` (build output
  handed to the host). `just run` and `just shell` create both on the host
  before mounting; the mount set is the `MOUNTS` justfile variable.

## Test kernel configuration

- defconfig plus the kernel's `debug.config` fragment: KASAN, UBSAN,
  kmemleak, DEBUG_OBJECTS, lockdep (PROVE_LOCKING, DEBUG_ATOMIC_SLEEP).
- DMA_API_DEBUG added where a driver maps DMA.

## Boot

- Host QEMU, machine type `virt`, HVF acceleration with the host CPU model.
- Headless, serial console on the terminal, user-mode networking.
- Inputs: the kernel `Image` and a busybox initramfs, both built in the
  container and copied to the gitignored `out/` directory.
- x86_64, later, boots the same way under TCG emulation with no
  acceleration.

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

- `justfile`, `Containerfile`, the project documents,
  `drivers/` (mounted at `/work/drivers`), `out/` (gitignored build output,
  mounted at `/work/out`), `.claude-temp/` (gitignored scratch).

## Explicitly out of scope

- virtme-ng, and booting inside the Podman machine: either would require
  nested virtualization. The boot runs on the host.
