# ARCHITECTURE – linux-kernel-driver-sandbox

> Describes the implementation as built. `just --list` is the authoritative
> list of recipes; a recipe named here that is not listed there is a
> documentation defect.

Podman-machine ownership and the Homebrew install-failure contract are 
defined in CONVENTIONS.md and are cited, not restated, below.

## Host

- macOS on Apple Silicon (M3).
- Tools from Homebrew: `just` (runner), `podman` (build host), `qemu`
  (boot). See CONVENTIONS.md for the install-failure contract.

## Runner (`just`)

- Two justfiles, each executing where it is mounted (CONVENTIONS.md). The
  root `justfile` runs on the macOS host: machine lifecycle, image build,
  the container bridge, and the workflow entry points. `vdev/justfile`,
  reached through the read-only repository mount at `/work/vdev`, is run by
  the `just` in the image; it holds the kernel recipes and the
  `KERNEL_VERSION` pin. Both `import` `active_exercise.just` at the repo
  root, which sets `EXERCISE`, the active exercise (CONVENTIONS.md); the
  root reaches it by name, `vdev/justfile` as `../active_exercise.just`
  through the same read-only mount.
- `just run-vdev <cmd>` is the single bridge into the container: it fails
  with `dev box is not running: run 'just machine-vdev'` unless the machine
  is already running, then runs `<cmd>` in a fresh container with the
  `MOUNTS` set. It never starts the machine.
- Root workflow recipes (`kernel-fetch-vdev`, `kernel-config-vdev`,
  `kernel-build-vdev`, `kernel-clean-vdev`, `driver-vdev`,
  `driver-clean-vdev`, `generate-vdev`, `userspace-vdev`,
  `userspace-clean-vdev`, `compile-commands-vdev`, `initramfs-vdev`,
  `checkpatch-vdev`,
  `export-clang-format-vdev`) depend
  on `machine-vdev` and compose one line: `just run-vdev just --justfile
  /work/vdev/justfile EXERCISE=<active> <name>`, where `<name>` is the root
  recipe's name with the `-vdev` suffix removed. The `EXERCISE=` argument is
  the pass-through a nested `just` needs (CONVENTIONS.md "Test machine"),
  carried by the `VDEV_JUST` variable so a command-line override reaches
  the container. `format` runs on the host (see "Style tools"). The recipe
  dependency chain (build needs config needs fetch) lives in
  `vdev/justfile`, so one container run covers a workflow.
- `just test` is one development iteration: `stage` in `vdev/justfile`
  (the active exercise's modules and userspace, the compile database, then
  the initramfs, one container run) followed by `test-vtarget`. Its nested `just stage-vdev`
  carries the same `EXERCISE=` pass-through. Its exit status is the guest's
  `lkds-test` result.
- Neither justfile carries staleness logic of its own.
- Staleness ownership is split by target: kbuild owns kernel and module
  staleness; the podman build owns image layer caching; the
  `machine-vdev` target checks live state (`podman machine inspect`), not
  timestamps.
- The project's Makefiles are the kbuild Makefiles under
  `exercises/<name>/driver/`, needed for out-of-tree module builds
  (`make M=...`) and invoked from the `driver` recipe in `vdev/justfile`,
  and the plain Makefiles under `exercises/<name>/userspace/` invoked from
  its `userspace` recipe (see "Userspace programs").

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
  xz/zstd/lz4 compressors, `clang-format` and `clangd` (same major as
  clang; see "Editor language server"),
  `luajit` (the guest's script interpreter, staged into the initramfs),
  and `just` (runs `vdev/justfile`).
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
- Image and volume names carry the project prefix `lkds-`, as do the
  framework's artifacts inside the guest: the `init` marker line, the
  `lkds-test` script and its `/etc/lkds/tests` manifest. Exercise names
  stay with the exercise (`tcd_`).

## Storage

- Kernel source and build output live in Podman volumes, never on a host
  bind mount: host directories reach the machine over virtiofs, and a
  kernel build across that boundary is several times slower than on a
  volume.
- The named volume `KERNEL_VOLUME` (`lkds-kernel`) is mounted at `/kernel`,
  the container's working directory. Podman creates it on first use.
- Two host directories are bind-mounted: the repository root read-only at
  `/work` (exercise sources, `vdev/justfile`, everything the container
  reads) and `OUT_DIR` (`out/`) read-write at `/work/out` (the only
  writable path: build output handed to the host). `just run-vdev` and
  `just shell-vdev` create `out/` on the host before mounting; the mount
  set is the `MOUNTS` variable in the root justfile.

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
- `dma_api_debug.config` sets `CONFIG_DMA_API_DEBUG=y`: the kernel checks
  every DMA mapping against the API's rules and reports misuse in `dmesg`
  under the `DMA-API:` prefix. A test run's log should carry only the two
  boot-time banner lines with that prefix.

## Boot

- `just run-vtarget` runs host QEMU (`qemu-system-aarch64`): machine type
  `virt`, `-accel hvf`, `-cpu host`; CPUs and memory from the `VTARGET_CPUS`
  and `VTARGET_MEMORY` justfile variables.
- Devices come from the `VTARGET_DEVICES` justfile variable, a space-separated
  list of QEMU device names added as `-device <name>`; default two instances
  of `edu` with `dma_mask=0xffffffff`, QEMU's educational PCI device (vendor
  `0x1234`, device `0x11e8`, documented at `docs/specs/edu.rst` in the QEMU
  tree), so multi-device paths are exercised on every boot. `just VTARGET_DEVICES="" run-vtarget`
  boots with no device.
- Headless (`-nographic`): the guest's serial console `ttyAMA0` is the
  terminal; `Ctrl-A X` exits. `earlycon` on the kernel command line.
- `panic=1` on the command line with `-no-reboot`: a kernel panic ends the
  QEMU process instead of hanging or rebooting.
- Inputs: `out/Image` and `out/initramfs.cpio.gz`, both produced in the
  container. The recipe fails naming the producing recipe when either is
  absent. No networking flags yet; QEMU's default applies.
- `run-vtarget` and `test-vtarget` share one QEMU invocation, the private
  `vtarget-qemu` recipe, which holds the input guards and takes the kernel
  command line as its argument (`VTARGET_APPEND` is the default). It is a
  nested `just` call, so the callers pass the `VTARGET_*` values through
  explicitly (`VTARGET_QEMU`); a command-line override reaches it.
- `just test-vtarget` boots with the marker word `lkds_test` appended to
  the kernel command line, stdin from `/dev/null`. The kernel passes the
  unrecognised word through to init, which runs `lkds-test`, prints
  `lkds-test: exit <status>` and powers off, ending QEMU. The console is
  echoed and saved to `out/vtarget-test.log` (truncated first). The recipe
  passes only if that log contains `lkds-test: exit 0`; otherwise it prints
  the `lkds-test:` lines and the log path and fails. There is no watchdog:
  a hung guest is stopped with Ctrl-C at the terminal, and an unattended
  run wraps the recipe in an external `timeout`.
- x86_64, later, boots the same way under TCG emulation with no
  acceleration.
- Dynamic programs run in the guest: the initramfs carries the loader and
  the shared libraries each dynamic binary needs, copied from the image
  that built them (see "Initramfs"). This is the tier between the static
  busybox root and a full Debian root, and what an interpreter such as
  LuaJIT needs.

### Initramfs

- `vdev/initramfs/init`, a POSIX sh script: mounts proc, sysfs and devtmpfs,
  exports `LUA_PATH` (see "Userspace programs"),
  prints the marker `lkds: userspace reached` and `uname -r`, then, if
  `lkds_test` is a word of `/proc/cmdline`, runs `lkds-test`, prints
  `lkds-test: exit <status>` and `poweroff -f` (see "Boot"); otherwise
  `exec setsid cttyhack sh` for a shell with job control on the console.
- `just initramfs-vdev` stages `/bin/busybox` (the image's `busybox-static`,
  checked static with `file`), `/init`, the applet symlinks (installed under
  `chroot` so they target `/bin/busybox`) and the `bin`, `sbin`, `proc`,
  `sys`, `dev` directories in a container temp dir, then packs a gzipped
  newc cpio to `out/initramfs.cpio.gz`. Always rebuilds; independent of the
  kernel and module recipes.
- If `out/driver/` exists, every `.ko` in it is staged at `/lib/modules/`;
  otherwise the archive is built without modules and says so on stderr.
- The image's `/usr/bin/luajit` is staged at `/usr/bin/luajit`, always,
  with its runtime closure (below). It is the interpreter for the
  exercises' scripts, not a test: it never appears in the manifest.
- If `out/userspace/` exists, every file in it is classified by content,
  never by name: a file whose first two bytes are `#!` is a script and is
  staged at `/usr/bin/` mode 755 with no closure of its own (its shebang
  names the interpreter); otherwise `file` decides: an ELF executable
  (PIE included) is staged at `/usr/bin/`, an ELF shared object at
  `/lib/`, anything else fails the recipe. A subdirectory of
  `out/userspace/` other than `include/` is script support (Lua modules
  beside the scripts that `require` them): it is staged whole under
  `/usr/bin/` under its own name, never classified and never in the
  manifest. Otherwise the archive is built
  without userspace programs and says so on stderr.
  `out/userspace/include/`, if present, is excluded from that
  classification and staged whole to `/usr/include/`, preserving its
  per-exercise subdirectory; headers are not listed in
  `/etc/lkds/tests`. A script reads the exercise's API header from
  `/usr/include/<name>/` at runtime.
- Runtime closure: for `luajit` and every staged ELF executable and
  project library the recipe runs `ldd` in the build image, with
  `LD_LIBRARY_PATH` at
  `out/userspace/` so the exercise's own libraries resolve, and copies each
  `=>` target into `/lib/` (flat, dereferencing symlinks: glibc's default
  search covers `/lib`) and the interpreter to exactly its `PT_INTERP`
  path, `/lib/ld-linux-aarch64.so.1` on arm64. `linux-vdso` is skipped; a
  `not found`, an interpreter outside `/lib` (an absolute `NEEDED`, for
  instance) or an unrecognised `ldd` line fails the recipe. A static binary
  (`ldd`: "not a dynamic executable") is staged with no closure, so static
  and dynamic programs coexist in one root.
- `vdev/initramfs/lkds-test`, staged executable at `/usr/bin/lkds-test`,
  always: loads every `.ko` staged at `/lib/modules/`, runs every command
  named in the `/etc/lkds/tests` manifest, and prints a one-line summary.
  Exits 0 if every test passed, 1 if any failed.
- `/etc/lkds/tests` lists the basename of every executable and script
  `initramfs-vdev` staged from `out/userspace/`, one per line, and never a
  library nor `luajit`; it is written only when `out/userspace/` existed
  at staging time. Executables come first, then scripts, each group in
  name order, so the compiled smoke test runs before the scripted suite.

## Debugging

- QEMU exposes its gdbstub on a host port.
- gdb runs inside the build container, next to the `vmlinux` in the build
  volume, and connects to the host port. How the container reaches that
  host port is not yet verified.

## Driver code

- One module per exercise: `exercises/<name>/driver/` holds the sources
  and a kbuild `Makefile` (`obj-m += <name>.o`). The kernel tree path and
  `M=` come from the recipe, not the Makefile.
- `just driver-vdev` runs `make -C KERNEL_SRC
  M=/work/exercises/<name>/driver MO=/work/out/driver-build/<name>
  modules` for the active exercise, against the in-tree build in the
  volume; it fails with `exercise '<name>' not found under /work/exercises`
  if the exercise directory is missing, if `driver/Makefile` is missing,
  and naming `kernel-build` if `Module.symvers` is absent. `MO=` sends
  every kbuild artifact to the output tree, so the source tree is never
  written and is mounted read-only. The resulting `.ko` files are copied
  to `out/driver/` (stale `.ko` files cleared first, so it holds only the
  active exercise's). `just driver-clean-vdev` removes
  `out/driver-build/` and `out/driver/` whole, every exercise's build
  tree included.
- `just initramfs-vdev` places the `.ko` files at `/lib/modules/` in the
  guest; load with `insmod /lib/modules/<name>.ko`, unload with `rmmod`.
  Modules are built for this kernel tree only, with no version
  compatibility shims.

## Userspace programs

- One userspace tree per exercise: `exercises/<name>/userspace/lib/` holds
  the library sources and `exercises/<name>/userspace/app/` the
  executable's, each with a plain GNU Makefile (not kbuild) that includes
  the shared `exercises/cpp.mk`, honours `CC`, `CXX`, `OUT` and
  `DRIVER_INCLUDE`, and writes only under `OUT`. The products may be
  dynamic: a PIE executable `<name>` linking `lib<name>*.so` by `SONAME`;
  the initramfs carries their runtime closure (see "Initramfs"). Files
  under an optional `exercises/<name>/userspace/script/` ship as-is, with
  no build step, and run as tests through `lkds-test`; each must start
  with a `#!` line naming its interpreter, and `/usr/bin/luajit` is the
  interpreter the guest provides today. Such a script reads the
  exercise's API header from `/usr/include/<name>/` at runtime.
  Subdirectories of `script/` hold modules the scripts `require`; they
  ship whole and are never run. `init` exports `LUA_PATH` as
  `/usr/bin/?.lua;;` so `require("binding.x")` resolves to
  `/usr/bin/binding/x.lua` from any cwd, the trailing `;;` keeping
  LuaJIT's default path behind it. The
  contract is in CONVENTIONS.md.
- `just userspace-vdev` runs `make -C /work/exercises/<name>/userspace/lib`
  then `make -C /work/exercises/<name>/userspace/app`, each with `CC=clang
  CXX=clang++ OUT=/work/out/userspace-build/<name>
  DRIVER_INCLUDE=/work/exercises`, for the active exercise (failing if the
  exercise directory, its `lib/Makefile` or its `app/Makefile` is
  missing), then copies the executable `<name>` and every `lib*.so*` from
  that tree, the whole `exercises/<name>/userspace/script/` tree
  (subdirectories included), and every `lib/*.h` header (to
  `out/userspace/include/<name>/`), to `out/userspace/`, which holds only
  what the initramfs ships (cleared first). It does not depend on the
  kernel recipes.
  `just userspace-clean-vdev` removes `out/userspace-build/` and
  `out/userspace/` whole, every exercise's intermediate tree included.
- `just initramfs-vdev` places the executables and scripts at `/usr/bin/`
  in the guest, which is on busybox's default `PATH`, the libraries at
  `/lib/`, and the headers at `/usr/include/<name>/`.
  `exercises/tiny_compute/userspace/` is the first test exercise.

## API generation

- An exercise's userspace API is defined once, in
  `exercises/<name>/userspace/api_def/<api>.adef.toml`, and the artifacts
  every consumer needs are generated from it: the C header, a translation
  unit of `static_assert` lines pinning library constants to the driver's
  UAPI header, and a LuaJIT base module carrying the `ffi.cdef` text as a
  long string. A header-only C++ wrapper is a planned fourth emitter. The
  kernel ioctl header is never generated; its shape is too far from a
  userspace API's, and it is hand-written UAPI under `driver/`.
- The definition format, as the loader reads it: `[general]` with
  `name`, `namespace` and `version`; `[untyped_bit_const]` with bit
  indices, a string list composing named constants; `[typed_const.<enum>]`
  with explicit values; `[opaque_ref.<name>]`; `[struct.<name>]` with
  typed fields; `[function.<name>]` with `return` and parameters in
  document order, each a bare type string or an inline table with `type`
  and attributes (`outref`, `inref`, `nullsafe`, `docstring`);
  `[driver_data]` naming the driver header and, under `const_pins`, the
  driver symbol each constant must equal. `docstring` and `return` are
  reserved keys at every level. Type names are one namespace across
  enums, opaque refs and structs. Parameter order is document order,
  which `tomllib` preserves because Python dicts do; the loader states
  that reliance.
- The generator is `vdev/api_gen/`, a standard-library-only Python
  package run in the container as `python3 -m api_gen <definition>
  --generated <dir>` with `PYTHONPATH=/work/vdev` and
  `PYTHONDONTWRITEBYTECODE=1`, since `/work/vdev` is read-only and Python
  would otherwise try to write `__pycache__` beside it. Outputs are build
  products at `out/userspace-build/<name>/generated/`, named by the
  definition's stem: `<stem>.h`, `<stem>_pins.cpp`, `<stem>.lua`. The
  current package is a stub that validates the definition parses and
  writes empty placeholders at those paths; the emitters are the next
  step. A per-API hooks module beside the definition is reserved for
  peculiarities, its interface to be cut from the first real case.
- `just generate-vdev` runs the `generate` recipe in `vdev/justfile`:
  every `api_def/*.adef.toml` through the generator, then `clang++
  -fsyntax-only` on each `<stem>_pins.cpp` with the exercises directory,
  the generated directory and `lib/` on the include path. That compile is
  the ABI pin check: a constant that disagrees with `tcd_ioctl.h` fails
  here, before the library or the app builds. An exercise with no
  definitions passes with a note. `userspace` depends on `generate`, so
  `stage` and `just test` run it.
- `exercises/cpp.mk` adds `-I$(OUT)/generated`, derived from the `OUT`
  it already receives, so `lib/` and `app/` sources include the generated
  header by name. A quoted include searches the including file's
  directory first, so while the hand-written `lib/tcdl_api.h` exists it
  wins over the empty placeholder.
- Staging of generated artifacts into the initramfs, the Lua base module
  to `out/userspace/binding/` and the generated header to
  `out/userspace/include/<name>/`, is written into the `userspace` recipe
  as commented-out lines and stays disabled until the generator emits
  real files; enabling it while the placeholders are empty would stage an
  empty header over the real one.
- The implementation of the API (`lib/tcdl_api.cpp`) stays hand-written;
  the generator will emit a stub of it once, to be copied into `lib/` when
  absent, and never touch it after.

## Style tools

- `just checkpatch-vdev` runs the kernel tree's
  `scripts/checkpatch.pl --no-tree --terse -f` over every `*.c` and `*.h`
  under the active exercise's `exercises/<name>/driver/` (a missing
  exercise fails with `exercise '<name>' not found under /work/exercises`).
  Its exit status is checkpatch's own: nonzero on any error or warning. It
  fails naming `kernel-fetch` when the tree is absent.
- `just format` runs on the host: the Homebrew `clang-format` with the
  kernel tree's `.clang-format`, exported to `out/clang-format` by
  `just export-clang-format-vdev` (a prerequisite, no-op once present),
  over every `*.c` and `*.h` under the active exercise's
  `exercises/<name>/driver/`. It rewrites files in place. It
  runs on the host because a rewrite from inside the container replaces
  the file with root's umask and drops the group-write bit the IDE needs.

## Editor language server

- The kernel headers, the generated config headers and the clang that
  built the module all live in the container, so clangd runs there and the
  host editor's LSP client talks to it over stdio. `just clangd-vdev`
  starts one: `podman run -i` (stdin attached, which `run-vdev` lacks)
  with the `MOUNTS` set, running the image's `clangd` with
  `--compile-commands-dir=/work/out` and `--path-mappings=<repo>=/work`,
  so every path the editor sends is translated to the container view and
  every path clangd returns is translated back. Extra arguments go to
  clangd. It requires the machine to be running and never starts it.
- `out/compile_commands.json` is produced by the `compile-commands` recipe
  in `vdev/justfile` (`just compile-commands-vdev` on the host; `stage`,
  and so `just test`, runs it after `driver` and `userspace`). Module
  entries come from the kbuild `.cmd` files under
  `out/driver-build/<name>/` through the kernel tree's
  `scripts/clang-tools/gen_compile_commands.py`; userspace entries come
  from the per-object fragments `exercises/cpp.mk` has clang emit with
  `-MJ` under `out/userspace-build/<name>/`. The recipe fails naming
  `driver` or `userspace` when either input is absent. Make does not
  track `cpp.mk` as a prerequisite, so a change to its flags needs
  `just userspace-clean-vdev` before the fragments reflect it.
- Paths under `/kernel` have no host counterpart: a diagnostic or a
  go-to-definition into a kernel header returns a container path the
  host cannot open. That is the one gap; closing it would mean a host
  bind mount for the kernel tree, which "Storage" rules out for build
  speed.
- The editor runs as the primary user and the Podman machine belongs to
  `agent-user` (CONVENTIONS.md), so the launcher crosses accounts. The
  editor's LSP client is configured with the command
  `sudo -n -H -u agent-user /opt/homebrew/bin/just --justfile
  <repo>/justfile clangd-vdev` in place of `clangd`. `-H` is load-bearing:
  macOS sudo keeps the caller's `HOME`, and podman refuses to run with a
  `~/.config` it does not own. For Zed that is
  `.zed/settings.json` at the repo root, `lsp.clangd.binary` with `path`
  and `arguments`; the justfile path there is absolute because Zed
  substitutes no workspace variable into it. The file names the host's
  account and checkout path, so it is gitignored and README.md carries
  the template. The same file pins
  `language_servers` for C and C++ to `clangd` and excludes
  `sourcekit-lsp`: with the Swift extension installed, Zed otherwise hands
  C files to Xcode's `sourcekit-lsp`, which spawns Xcode's clangd with no
  compile database, and the `clangd` binary setting never applies. The
  absolute `just` path is
  deliberate: a GUI-launched editor does not inherit the shell's Homebrew
  `PATH`, and for the same reason the root justfile prepends
  `/opt/homebrew/bin` to `PATH` for every recipe, so `podman` resolves
  inside `guard-vdev`. The sudoers rule that lets `-n` succeed is host
  state the primary user sets by hand (CONVENTIONS.md "Build
  environment").
- clangd's background index lands in `out/.cache/clangd/`, beside the
  compile database.

## Repo layout

- The repository root is mounted read-only at `/work`: `justfile`,
  `active_exercise.just` (the `EXERCISE` selection both justfiles import),
  `vdev/justfile`, `vdev/initramfs/`, `vdev/kernel-config/` and
  `vdev/api_gen/` (the API generator, see "API generation"),
  `Containerfile`, the project documents, `exercises/cpp.mk` and one
  `exercises/<name>/` tree per exercise (`SPEC.md`, `ARCHITECTURE.md`,
  `driver/`, `userspace/` with `api_def/`, `lib/`, `app/` and `script/`;
  `tiny_compute` is the first), `out/`
  (gitignored build output, mounted read-write at `/work/out`),
  `.zed/settings.json` (gitignored, Zed's clangd launcher, see "Editor
  language server"), `.claude-temp/` (gitignored scratch).

## Explicitly out of scope

- virtme-ng, and booting inside the Podman machine: either would require
  nested virtualization. The boot runs on the host.
