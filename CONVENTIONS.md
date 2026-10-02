# CONVENTIONS – linux-kernel-driver-sandbox

Rules only. Detail lives in ARCHITECTURE.md; a quoted section name refers to it.

## Decisions

- Take the most-travelled path: default toolchain, default configuration, documented workflow.
- Step off it only as a deliberate learning choice, and only after the default path has worked.
- One new choice at a time: make the next only once the previous one's consequences are explored and understood.

## Naming

- Exercise, driver directory, file and module names are snake_case, matching what `lsmod`, sysfs and stack traces show.
- Hyphens only where the kernel requires them: compatible strings and device tree names.
- A recipe's suffix names what it acts on, not where it runs: `machine-vdev` and `machine-stop-vdev` run on the host and act on the Podman VM.

## Runner

- A recipe runs where its justfile is mounted: the root `justfile` on the macOS host, `vdev/justfile` in the build container.
- The root `justfile` knows the container's layout only through its mount targets: `MOUNTS`, the `VDEV_JUST` runner path, and the path mapping `clangd-vdev` passes. `vdev/justfile` names no host path or host tool.
- The root composes workflows from host recipes and `run-vdev`; `vdev/justfile` does the work.
- The active exercise is `EXERCISE` in `active_exercise.just`; every build, stage and test recipe acts on it alone; `format`, `format-check` and `checkpatch-vdev` (and the pre-commit hook) cover every exercise's `driver/`; and the `*-clean-vdev` recipes remove every exercise's tree. `just EXERCISE=<name> <recipe>` overrides it for one run.
- One exercise per boot, until device-to-driver assignment exists.
- Overrides do not reach a nested `just`: a root recipe that invokes `just` passes every overridable variable it depends on as `VAR=value`, as `VTARGET_QEMU` does.
- Options precede overrides on the command line: `just --dry-run VAR=value recipe`.

## Build environment

- The Podman machine belongs to `agent-user`; every `podman machine` command against it, by anyone, runs as `agent-user`.
- Host state outside the project changes only by the primary user's hand: Homebrew installs, the sudoers rule for the clangd launcher ("Editor language server").
- A target missing a host tool exits nonzero naming the tool and its `brew install` line; it never installs.
- No target's success path mutates host state outside the project directory and the Podman machine.
- A bind-mounted host path needs `agent-user` read and search permission on every directory from `/Users` down; search-only fails.
- Container recipes write only to `/work/out`: assemble in a container-local temp dir; module builds pass `MO=` ("Storage").
- Machine sizing is the `MACHINE_*` justfile variables; to apply a change, `podman machine rm` then `just machine-vdev`. No target runs `podman machine set`.
- Kernel config choices live in `vdev/kernel-config/*.config` fragments ("Test kernel configuration"); never hand-edit `.config`. After a fragment change, run `kernel-config-vdev`, then rebuild.

## Exercise userspace ("Userspace programs")

- Makefiles under `exercises/<name>/userspace/` are plain GNU make, not kbuild; they write only under `OUT` and name no container or repository path.
- `lib/` and `app_cpp/` include `exercises/cpp.mk` and take `CC`, `CXX`, `OUT`, `DRIVER_INCLUDE`; `api_def/` includes `exercises/gen.mk` and takes `OUT`, `API_GEN`.
- Test programs live in `app_<language>/` (`app_cpp/`, `app_rs/`, `app_lua/`), one directory per language, so a future language gets its own directory rather than a shared generic name.
- A `lib/` or `app_rs/` may instead be a cargo crate (`Cargo.toml`); both take `API_GEN_RUST_DIR` and `CARGO_TARGET_DIR`, `lib/` also takes `DRIVER_INCLUDE` (for bindgen) and `app_rs/` also takes `API_LIB_DIR`. `lib/` never holds both a Makefile and a `Cargo.toml`; `app_rs/` is always a cargo crate, so one without a `Cargo.toml` fails the build.
- A cargo crate carries its `Cargo.lock`: the container mounts the repository read-only, so cargo builds `--locked` and cannot write one on the fly.
- UAPI headers are included as `<name>/driver/*.h` (`DRIVER_INCLUDE` is `exercises/`).
- Products: a test program is named after its directory, `$(OUT)/app_cpp` from `app_cpp/` and `$(OUT)/app_rs` from `app_rs/`, since one exercise is staged per boot and only the library carries the exercise name: `$(OUT)/lib<name>*.so`, each with a `SONAME` equal to its file name, from a make-built or a cargo `lib/`. Anything else under `OUT` is intermediate.
- The executable links a library by `SONAME`, never by path; static linking is not required.
- The library's public header is the generated one, shipped to `/usr/include/<name>/`; `lib/*.h` are the implementation's own and are not shipped.
- `app_lua/` has no build step: its entry point is `app_lua/app_lua.lua`, a `#!` script naming its interpreter (the guest provides `/usr/bin/luajit`); a top-level `*.lua` ships under its stem, so it lands at `/usr/bin/app_lua` and runs as the test while the source keeps the extension the editor's language services need. Any other top-level file there would run as a test too, so none exists and the build refuses one.
- Its subdirectory `app_lua/lib_lua/` holds the Lua sources the entry point requires, shipped whole to `/usr/bin/lib_lua/` and never run; the guest's `LUA_PATH` resolves `require("lib_lua.<file>")` from any cwd, as it does `binding.<stem>` for the generated module.

## API generation ("API generation")

- `vdev/api_gen/` is framework code.
- The generator and its tests run only in the container (`just generate-vdev`, `just api-gen-test-vdev`); never run `python3` on the host against `vdev/api_gen/`. A host run proves nothing about the pinned toolchain the outputs are built and formatted with.
- One `.adef.toml` per exercise: one definition, one `gendeps` call, one set of outputs. `gen.mk` refuses `api_def/` with more or none.
- After changing the generator or `cpp.mk` flags, run `userspace-clean-vdev`.
- Generated files are build products under `out/`, never written into the source tree.
- The ioctl header under `driver/` is hand-written UAPI; never generate it.
- Pin every constant the library relays from the driver as a member of `[_wrapped_api._pinned_value]`; a relayed constant without a pin is a review finding.

## Style and editor

- Driver sources follow kernel coding style; `format` applies it ("Style tools"), and a driver change is not done until `checkpatch-vdev` is clean.
- Git hooks are tracked and inert under `githooks/`, one file per hook name; they take effect once the human runs `just install-hooks`, which copies them into `.git/hooks/` beside whatever other packages installed there, and `just uninstall-hooks` removes only those ("Style tools"). `just verify` runs the installed pre-commit hook; `just format-check` is `format`'s non-rewriting check, for anyone but the human running the hook (AGENTS.md reserves the rewrite for the human).
- Editor C/C++ intelligence comes from the image's clangd through `just clangd-vdev`, never a host clangd ("Editor language server").
- Markdown prose is one paragraph or list item per line, never hard-wrapped: a rendered page looks the same, and an edit or a diff touches one line.

## Test machine ("Boot")

- `out/initramfs.cpio.gz` is a snapshot: after `driver-vdev` or `userspace-vdev`, run `initramfs-vdev` before `run-vtarget`.
- `out/Image` comes only from `kernel-build-vdev`; `stage` and `test` do not build it.
- Stdin piped into `run-vtarget` at launch is lost. A scripted session waits for the shell prompt before its first line, and lets the last output drain before its timeout ends QEMU.
- The only console contract is `lkds-test: exit N`; `test-vtarget` passes only on `exit 0`.
