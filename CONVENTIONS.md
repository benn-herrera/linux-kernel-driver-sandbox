# CONVENTIONS – linux-kernel-driver-sandbox

## Decision practice

- Stay on the most-travelled path: the default toolchain, the default
  configuration, the documented workflow. Step off it only as a deliberate
  learning choice, and only after the default path has been visited
  successfully.
- One new choice at a time. A choice is not made until the consequences of
  the previous one have been explored and understood.

## Naming

- Exercise, driver directory, file and module names use snake_case, so the
  spelling in the tree matches what `lsmod`, sysfs and stack traces show.
  Hyphens appear only where the kernel requires them: compatible strings
  and device tree names.
- A recipe executes where its justfile is mounted. The root `justfile` runs
  on the macOS host and never names a container path outside its mount
  specifications. `vdev/justfile` is mounted into the build container and
  runs there; it never names a host path or a host tool. The root composes
  workflows from host recipes and `run-vdev`; the module does the work.
  `machine-vdev` and `machine-stop-vdev` manage the Podman VM from the
  host; the suffix names what they act on.

## Style

- Driver and userspace sources follow kernel coding style. `format` (on
  the host) applies it; `checkpatch-vdev` must be clean before a driver
  change is considered done.

## Build environment

- A Podman machine is per-account state. This project's machine belongs to
  `agent-user`, and every `podman machine` command against it, by anyone,
  runs as `agent-user`. A machine created from the primary user's shell is
  invisible to the project.
- Host tools come from Homebrew, whose prefix the primary user owns.
  Installing one is the single exception to running project commands as
  `agent-user`: only the primary user can, and only by hand. A runner target
  that needs a missing tool exits nonzero naming the tool and its
  `brew install` line; it never installs. No target's success path mutates
  host state outside the project directory and the Podman machine.
- The machine's file share into containers is served on the macOS side as
  `agent-user`. A host path can be bind-mounted only if `agent-user` has
  read and search permission on every directory from `/Users` down to it;
  traverse-only on an ancestor makes the mount fail with permission denied.
- The repository is mounted read-only at `/work` inside the container;
  `/work/out` is the only writable path. A recipe that assembles files
  stages them in a container-local temp dir and writes only to `/work/out`.
  Module builds pass `MO=` so kbuild's artifacts land there too.
- Kernel configuration choices live in `vdev/kernel-config/*.config`
  fragments merged over defconfig and debug.config by `kernel-config`.
  `.config` is never edited by hand; a change to a fragment is followed by
  `kernel-config-vdev` and a rebuild.
- An exercise's userspace tree, `exercises/<name>/userspace/`, builds
  through plain Makefiles (not kbuild fragments) that take `CC`, `CXX`,
  `OUT` and `DRIVER_INCLUDE` (the `exercises/` directory, so the UAPI
  headers resolve as `<name>/driver/*.h`) and write only under `OUT`. It
  produces the executable
  `$(OUT)/<name>`, named after the exercise directory, and optionally
  shared libraries `$(OUT)/lib<name>*.so` each carrying a `SONAME` equal to
  its file name; the executable links a library by that name, never by
  path. Static linking is not required. Anything else written under `OUT`
  is intermediate. The Makefiles know no container or repository path.
  `exercises/<name>/userspace/lua/*.lua` are staged as-is, without a build step,
  and must start with `#!/usr/bin/luajit` to run as tests.
- The active exercise is `EXERCISE` in `active_exercise.just` at the repo
  root, imported by both justfiles. Every build, stage, test and style recipe
  operates on that exercise only; `just EXERCISE=<name> <recipe>` overrides it
  for one run. Several exercises in one boot would contend for the same `edu`
  devices, so running more than one is not supported until device-to-driver
  assignment exists.
- Podman machine sizing lives in the `MACHINE_*` variables in the justfile.
  Changing them does not resize an existing machine: remove it with
  `podman machine rm` and run `just machine-vdev` again. No target runs
  `podman machine set`.

## Test machine

- `out/initramfs.cpio.gz` is a snapshot. After `driver-vdev`, run
  `initramfs-vdev` before `run-vtarget`, or the guest loads the previous
  build of the module.
- `out/Image` comes only from `kernel-build-vdev`; `stage` and `test` do
  not produce it. A boot recipe that finds it missing names that recipe.
- Stdin piped into `run-vtarget` at launch is delivered before the guest
  UART exists and is lost. A scripted console session waits for the shell
  prompt before sending its first line, and lets the last command's output
  drain before its timeout ends QEMU, or the final line is lost.
- The guest reports a test run to the host through one line on the
  console, `lkds-test: exit N`, printed by `init` after `lkds-test`
  returns. `test-vtarget` passes only on `exit 0`; nothing else in the
  console output is a contract.
- A command-line variable override (`just VAR=value recipe`) does not
  reach a `just` invoked from inside a recipe. A root recipe that invokes
  `just` recursively passes every overridable variable it depends on
  explicitly as `VAR=value` arguments, the way `VTARGET_QEMU` does. On the
  command line, options precede overrides: `just --dry-run VAR=value
  recipe`; `just` reads anything after the first override as a recipe name.
