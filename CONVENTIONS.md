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

- Driver and userspace sources follow kernel coding style. `format-vdev`
  applies it; `checkpatch-vdev` must be clean before a driver change is
  considered done.

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
- `/work/vdev` is read-only inside the container. A recipe there that
  assembles files stages them in a container-local temp dir and writes only
  to `/work/out`.
- Kernel configuration choices live in `vdev/kernel-config/*.config`
  fragments merged over defconfig and debug.config by `kernel-config`.
  `.config` is never edited by hand; a change to a fragment is followed by
  `kernel-config-vdev` and a rebuild.
- A module build leaves kbuild artifacts, including the generated
  `<name>.mod.c`, inside `drivers/<name>/`. A recipe that globs sources
  there excludes them.
- A `userspace/<name>/Makefile` is a plain Makefile that takes `CC` and
  `OUT`, produces static binaries, and writes only under `OUT`. It is not a
  kbuild fragment.
- Podman machine sizing lives in the `MACHINE_*` variables in the justfile.
  Changing them does not resize an existing machine: remove it with
  `podman machine rm` and run `just machine-vdev` again. No target runs
  `podman machine set`.

## Test machine

- `out/initramfs.cpio.gz` is a snapshot. After `modules-vdev`, run
  `initramfs-vdev` before `run-vtarget`, or the guest loads the previous
  build of the module.
- Stdin piped into `run-vtarget` at launch is delivered before the guest
  UART exists and is lost. A scripted console session waits for the shell
  prompt before sending its first line, and lets the last command's output
  drain before its timeout ends QEMU, or the final line is lost.
