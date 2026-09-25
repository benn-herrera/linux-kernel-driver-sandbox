# ARCHITECTURE – linux-kernel-driver-sandbox

> Describes the implementation as built. `just --list` is the authoritative
> list of recipes; a recipe named here that is not listed there is a
> documentation defect.

Podman-machine ownership and the Homebrew install-failure contract are defined in CONVENTIONS.md and are cited, not restated, below.

## Host

- macOS on Apple Silicon.
- Tools from Homebrew: `just` (runner), `podman` (build host), `qemu` (boot), `clang-format` (style). See CONVENTIONS.md for the install-failure contract.

## Runner (`just`)

- Two justfiles, each executing where it is mounted (CONVENTIONS.md "Runner"). The root `justfile` runs on the macOS host: machine lifecycle, image build, the container bridge, and the workflow entry points. `vdev/justfile` runs inside the container, reached read-only at `/work/vdev`, and holds the kernel and exercise recipes plus the `KERNEL_VERSION` pin. Both `import` `active_exercise.just` at the repo root, which sets `EXERCISE`.
- `just run-vdev <cmd>` is the only bridge into the container. Its `guard-vdev` prerequisite fails if `podman` is missing from `PATH`, if `podman machine inspect` itself errors (printing podman's message), or if the machine is not running (`dev box is not running (<state>): run 'just machine-vdev'`); it never starts the machine.
- Root workflow recipes (`kernel-fetch-vdev`, `kernel-config-vdev`, `kernel-build-vdev`, `kernel-clean-vdev`, `driver-vdev`, `driver-clean-vdev`, `api-gen-test-vdev`, `generate-vdev`, `userspace-vdev`, `userspace-clean-vdev`, `compile-commands-vdev`, `initramfs-vdev`, `checkpatch-vdev`, `export-clang-format-vdev`) depend on `machine-vdev` and compose one line: `just run-vdev just --justfile /work/vdev/justfile EXERCISE=<active> <name>`, `<name>` being the root recipe's name with `-vdev` removed. `EXERCISE=` is passed explicitly because overrides do not reach a nested `just` (CONVENTIONS.md "Runner"), carried by the `VDEV_JUST` variable. `format` runs on the host (see "Style tools"). Recipe dependencies (build needs config needs fetch) live in `vdev/justfile`, so one container run covers a workflow.
- `just test` is one development iteration: `stage-vdev` (the active exercise's modules and userspace, the compile database, then the initramfs, one container run), then `test-vtarget`. Its exit status is the guest's `lkds-test` result.
- Staleness is split by target: kbuild owns kernel and module staleness, the podman build owns image layer caching, `machine-vdev` checks live state (`podman machine inspect`) rather than timestamps.
- The project's own Makefiles are the kbuild `Makefile`s under `exercises/<name>/driver/` and the plain Makefiles under `exercises/<name>/userspace/` (see "Userspace programs").

## Build host: Podman machine

- Apple Virtualization provider, the account default machine. See CONVENTIONS.md "Build environment" for ownership.
- Created and started by `just machine-vdev`, sized by the `MACHINE_CPUS`, `MACHINE_MEMORY_MIB`, `MACHINE_DISK_GB` justfile variables. Changing a size variable does not resize an existing machine (CONVENTIONS.md "Build environment").

## Build environment: container image

- The Containerfile (repo root) defines the toolchain: clang/LLVM with lld, Rust (`rustc`, `rust-src`, `rustfmt`, `rust-clippy`), `bindgen`, `clang-format` and `clangd` (see "Editor language server"), `luajit` (staged into the initramfs), `just` (runs `vdev/justfile`), `git`, `ca-certificates` and `file`; see the Containerfile for the full package list. None of these are version-pinned: they are whatever `apt-get install` resolves from `debian:trixie-slim` at image build time.
- `vdev/justfile`'s `MAKE` variable comment states why every kbuild invocation runs `LLVM=1`.
- Base image: `docker.io/library/debian:trixie-slim`, built by `just image-vdev` as `IMAGE` (`lkds-build`) from the Containerfile on stdin, with no build context.
- Processes in the container run as root; under rootless Podman that is the machine-side account, so bind-mounted files land owned by the host user.
- The target is ARM64: the guest runs near-native under HVF on the Apple Silicon host. An x86_64 cross-gcc is added when that platform comes into scope.
- Image and volume names carry the project prefix `lkds-`, as do the framework's artifacts inside the guest: the `init` marker line, the `lkds-test` script and its `/etc/lkds/tests` manifest. Exercise names stay with the exercise (`tcd_`).

## Storage

- Kernel source and build output live in Podman volumes, never on a host bind mount: a kernel build over the host's virtiofs mount is several times slower than on a volume.
- The named volume `KERNEL_VOLUME` (`lkds-kernel`) is mounted at `/kernel`, the container's working directory; Podman creates it on first use.
- Two host directories are bind-mounted: the repository root read-only at `/work` and `OUT_DIR` (`out/`) read-write at `/work/out`, the only writable path. `just run-vdev` and `just shell-vdev` create `out/` on the host before mounting; the mount set is `MOUNTS` in the root justfile.

## Kernel source and build

- Source is the stable release tarball pinned by `KERNEL_VERSION` in `vdev/justfile`, fetched from kernel.org by `just kernel-fetch-vdev`, verified against `sha256sums.asc`, and extracted to `KERNEL_SRC` (`/kernel/linux-<version>`) in the volume. A present tree means no fetch.
- The build is in-tree (no `O=`) with clang: every make invocation in `vdev/justfile` goes through its `MAKE` variable. `just kernel-config-vdev` runs `make defconfig debug.config` in `KERNEL_SRC`, merges the project fragments (see "Test kernel configuration") and fails unless `CONFIG_RUST` ends up `y`; `just kernel-build-vdev` builds the `Image` and `modules` targets and copies `Image` to `out/`. The `modules` target produces `Module.symvers`, which out-of-tree builds need. `just kernel-clean-vdev` is `make clean`, keeping `.config`.

## Test kernel configuration

- defconfig plus the kernel's `debug.config` fragment: KASAN, UBSAN, kmemleak, DEBUG_OBJECTS, lockdep (PROVE_LOCKING, DEBUG_ATOMIC_SLEEP).
- The project's own fragments under `vdev/kernel-config/*.config`, merged on top by `scripts/kconfig/merge_config.sh -m` then `make olddefconfig`. `rust.config` sets `CONFIG_RUST=y`. Kconfig drops `CONFIG_RUST=y` silently when the toolchain check fails, so `kernel-config` verifies it with `scripts/config --state RUST`.
- `dma_api_debug.config` sets `CONFIG_DMA_API_DEBUG=y`: the kernel checks every DMA mapping against the API's rules and reports misuse in `dmesg` under the `DMA-API:` prefix. A test run's log should carry only the two boot-time banner lines with that prefix.

## Boot

- `just run-vtarget` runs host QEMU (`qemu-system-aarch64`): machine type `virt`, `-accel hvf`, `-cpu host`; CPUs and memory from `VTARGET_CPUS` and `VTARGET_MEMORY`.
- Devices come from `VTARGET_DEVICES`, a space-separated list of QEMU device names added as `-device <name>`; default two instances of `edu` with `dma_mask=0xffffffff`, QEMU's educational PCI stand-in device, so multi-device paths are exercised on every boot. `just VTARGET_DEVICES="" run-vtarget` boots with no device.
- Headless (`-nographic`): the guest's serial console `ttyAMA0` is the terminal; `Ctrl-A X` exits. `earlycon` is on the kernel command line.
- `panic=1` with `-no-reboot`: a kernel panic ends the QEMU process instead of hanging or rebooting.
- Inputs: `out/Image` and `out/initramfs.cpio.gz`, both produced in the container; the recipe fails naming the producer when either is absent. No networking flags yet.
- `run-vtarget` and `test-vtarget` share one private recipe, `vtarget-qemu`, which holds the input guards and takes the kernel command line as its argument (`VTARGET_APPEND` is the default). It is a nested `just` call, so callers pass the `VTARGET_*` values through explicitly (`VTARGET_QEMU`), and a command-line override still reaches it.
- `just test-vtarget` boots with the marker word `lkds_test` appended to the kernel command line, stdin from `/dev/null`. The console is echoed and saved to `out/vtarget-test.log` (truncated first); the recipe passes only if that log contains `lkds-test: exit 0`, otherwise it prints the `lkds-test:` lines and the log path and fails. No watchdog: Ctrl-C stops a hung guest; an unattended run wraps the recipe in `timeout`.
- x86_64, later, boots the same way under TCG emulation with no acceleration.
- Dynamic programs run in the guest: the initramfs carries the loader and the shared libraries each dynamic binary needs, copied from the image that built them (see "Initramfs").

### Initramfs

`vdev/justfile`'s `initramfs` recipe doc states the staging locations, content classification and manifest order in full; this covers what it does not.

- Busybox applets are installed under `chroot`, so busybox's own self-install targets `/bin/busybox` as the guest will see it, not the host path used to run it.
- Runtime closure: for `luajit` and every staged ELF executable and library, the recipe runs `ldd` in the build image (`LD_LIBRARY_PATH` at `out/userspace/` so the exercise's own libraries resolve), copying each `=>` target into `/lib/` (flat, dereferencing symlinks) and the interpreter to exactly its `PT_INTERP` path, `/lib/ld-linux-aarch64.so.1` on arm64. `linux-vdso` is skipped; a `not found`, an interpreter outside `/lib`, or an unrecognised `ldd` line fails the recipe. A static binary (`ldd`: "not a dynamic executable") gets no closure.
- `init` exports `LUA_PATH` as `/usr/bin/?.lua;;` so `require("binding.x")` resolves to `/usr/bin/binding/x.lua` from any cwd, the trailing `;;` keeping LuaJIT's default path behind it.
- The only console contract is the line `lkds-test: exit N`: `init` prints it after running `lkds-test` and before `poweroff -f`.

## Driver code

- One module per exercise: `driver/` holds the sources and a kbuild `Makefile` (`obj-m += <name>.o`); the kernel tree path and `M=` come from the recipe, not the Makefile.
- `just driver-vdev` runs `make -C KERNEL_SRC M=/work/exercises/<name>/driver MO=/work/out/driver-build/<name> modules` for the active exercise, against the in-tree build in the volume; it fails naming the missing exercise directory or `driver/Makefile`, and naming `kernel-build` if `Module.symvers` is absent. `MO=` sends every kbuild artifact to the output tree, so the read-only source tree is never written. The `.ko` files land in `out/driver/` (cleared first). `just driver-clean-vdev` removes `out/driver-build/` and `out/driver/` whole, every exercise's build tree included.
- `just initramfs-vdev` places the `.ko` files at `/lib/modules/` in the guest; load with `insmod /lib/modules/<name>.ko`, unload with `rmmod`. Modules are built for this kernel tree only, with no version compatibility shims.

## Userspace programs

- One userspace tree per exercise: `userspace/lib/` holds the library sources and `userspace/app/` the executable's, each with a plain GNU Makefile that includes the shared `exercises/cpp.mk` (CONVENTIONS.md "Exercise userspace"). Products may be dynamic: a PIE executable `<name>` linking `lib<name>*.so` by `SONAME`; the initramfs carries their runtime closure (see "Initramfs"). Files under an optional `userspace/script/` ship as-is and run as tests through `lkds-test`; a Lua script reaches the API through the generated module under `binding/` (see "API generation").
- `just userspace-vdev` runs `make -C lib` then `make -C app`, each with `CC=clang CXX=clang++ OUT=/work/out/userspace-build/<name> DRIVER_INCLUDE=/work/exercises`, for the active exercise, then copies the executable, every `lib*.so*` and the whole `script/` tree to `out/userspace/` (cleared first, so it holds only what the initramfs ships), then stages the generated `include/` and `binding/` subtrees onto it (see "API generation"). `lib/*.h` are the implementation's own and are not staged; the recipe does not depend on the kernel recipes. `just userspace-clean-vdev` removes `out/userspace-build/` and `out/userspace/` whole, every exercise's intermediate tree included.
- `just initramfs-vdev` places the executables and scripts at `/usr/bin/` in the guest (on busybox's default `PATH`), the libraries at `/lib/`, and the headers at `/usr/include/<name>/`. `exercises/tiny_compute/userspace/` is the first test exercise.

## API generation

An exercise's userspace API is defined once, in `exercises/<name>/userspace/api_def/<api>.adef.toml`. The definition format and every output's contract are `vdev/api_gen/SPEC.md`; the generator's internals are `vdev/api_gen/ARCHITECTURE.md`. This section covers only how generation fits the build.

- `just generate-vdev` runs the `generate` recipe in `vdev/justfile`: `make -C exercises/<name>/userspace/api_def`, whose Makefile includes `exercises/gen.mk`, the sibling of `cpp.mk`. `gen.mk` includes `generated/adef.mk`, written by the generator's `gendeps` mode for the exercise's one `*.adef.toml` (one per exercise; `gen.mk` refuses more or none): a `GENERATED` list in terms of `$(GEN)` and `$(BASE)` and one grouped rule making every output from the definition. Make remakes an out-of-date included makefile and restarts, so an edited definition regenerates `adef.mk` before `all` is evaluated. `userspace` depends on `generate`, so `stage` and `just test` run it. An exercise with no `api_def/Makefile` passes with a note.
- Outputs land at `out/userspace-build/<name>/generated/include/<name>/ <stem>.h` and `<stem>.hpp`, `generated/binding/<stem>.lua` and `generated/stub/<stem>.cpp`. `userspace` stages the `include/` and `binding/` subtrees whole onto `out/userspace/`, which `initramfs-vdev` ships to `/usr/include/<name>/` and `/usr/bin/binding/` respectively; `stub/` is never staged. `exercises/cpp.mk` adds `-I$(OUT)/generated/include/<exercise>`, so `lib/` and `app/` sources include the generated header by bare name, as they would their own; `-MMD` rebuilds any object whose header changed.
- The ABI pin check runs when the library compiles: the implementation defines the API's implementation macro before including the generated header, which brings in the driver's UAPI header and the pins' `static_assert` lines, so a constant that disagrees with the driver fails the library build.
- A change to the generator or to `cpp.mk`'s flags is followed by `userspace-clean-vdev` (CONVENTIONS.md "API generation").
- `just api-gen-test-vdev` runs the generator's own unit tests (`vdev/api_gen/ARCHITECTURE.md` "Tests") in the container.
- Not generated: the kernel ioctl header (hand-written UAPI under `driver/`) and the API's implementation (hand-written; the pins are the bridge).

## Style tools

- `just checkpatch-vdev` runs the kernel tree's `checkpatch.pl` over every `*.c` and `*.h` under the active exercise's `driver/`; its exit status is checkpatch's own. It fails naming `kernel-fetch` when the tree is absent.
- `just format` runs on the host: Homebrew's `clang-format` with the kernel tree's `.clang-format`, exported to `out/clang-format` by `export-clang-format-vdev` (a prerequisite, no-op once present), over the active exercise's `driver/`. It rewrites files in place, on the host, because a rewrite from inside the container replaces the file with root's umask and drops the group-write bit the IDE needs.

## Editor language server

- The kernel headers, generated config headers and the clang that built the module all live in the container, so clangd runs there; the host editor's LSP client talks to it over stdio via `just clangd-vdev`: `podman run -i` with `MOUNTS` set, running the image's `clangd` with `--compile-commands-dir=/work/out` and `--path-mappings=<repo>=/work` so every path translates in both directions. It requires the machine running and never starts it.
- The compile database it reads, `out/compile_commands.json`, comes from the `compile-commands` recipe, which `stage` (and so `just test`) runs after `driver` and `userspace`.
- Paths under `/kernel` have no host counterpart: a diagnostic or go-to-definition into a kernel header returns a container path the host cannot open. That is the one gap.
- The editor runs as the primary user while the Podman machine belongs to `agent-user` (CONVENTIONS.md "Build environment"), so the launcher crosses accounts; the root justfile prepends Homebrew's `/opt/homebrew/bin` to `PATH` for every recipe because a GUI-launched editor has no Homebrew on its own `PATH`. See README.md "Editor setup" for the launcher command, the Zed configuration (which also excludes `sourcekit-lsp` from claiming C files), and the sudoers rule.
- clangd's background index lands in `out/.cache/clangd/`, beside the compile database.

## Repo layout

- The repository root is mounted read-only at `/work`: `justfile`, `active_exercise.just` (the `EXERCISE` selection both justfiles import), `vdev/justfile`, `vdev/initramfs/`, `vdev/kernel-config/` and `vdev/api_gen/` (see "API generation"), `Containerfile`, the project documents, `exercises/cpp.mk` and `exercises/gen.mk`, and one `exercises/<name>/` tree per exercise (`SPEC.md`, `ARCHITECTURE.md`, `driver/`, `userspace/` with `api_def/`, `lib/`, `app/` and `script/`; `tiny_compute` is the first). `out/` (gitignored build output) is mounted read-write at `/work/out`. `.zed/settings.json` (gitignored, see "Editor language server") and `.claude-temp/` (gitignored scratch) are host-only.

## Explicitly out of scope

- virtme-ng, and booting inside the Podman machine: either would require nested virtualization. The boot runs on the host.
