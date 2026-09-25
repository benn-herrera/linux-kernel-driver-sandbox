set positional-arguments

import 'active_exercise.just'

# Homebrew's bin for every recipe: a GUI-launched editor reaching clangd-vdev has no Homebrew on its PATH.
export PATH := "/opt/homebrew/bin:" + env("PATH")

default:
  @just --list

AGENTS_REPO := "https://github.com/benn-herrera/adjagent.git"
AGENTS_DIR := ".claude" / file_stem(AGENTS_REPO)
MACHINE := "podman-machine-default"
MACHINE_CPUS := "8"
MACHINE_MEMORY_MIB := "8192"
MACHINE_DISK_GB := "60"
IMAGE := "lkds-build"
KERNEL_VOLUME := "lkds-kernel"
REPO_DIR := justfile_directory()
OUT_DIR := REPO_DIR / "out"
VTARGET_CPUS := "4"
VTARGET_MEMORY := "2G"
VTARGET_DEVICES := "edu,dma_mask=0xffffffff edu,dma_mask=0xffffffff"
VTARGET_APPEND := "console=ttyAMA0 earlycon panic=1"
# Command-line overrides never reach a nested just, so the boot recipe is invoked with the VTARGET_* values passed explicitly.
# Each is shell-quoted here, so recipes interpolate VTARGET_QEMU unquoted.
VTARGET_QEMU := "just " + quote("VTARGET_CPUS=" + VTARGET_CPUS) + " " + quote("VTARGET_MEMORY=" + VTARGET_MEMORY) + " " + quote("VTARGET_DEVICES=" + VTARGET_DEVICES) + " vtarget-qemu"
# one-shot testing target output
VTARGET_TEST_LOG := OUT_DIR / "vtarget-test.log"

# Each mount is shell-quoted here, so recipes interpolate MOUNTS unquoted.
MOUNTS := "-v " + quote(KERNEL_VOLUME + ":/kernel") + " -v " + quote(REPO_DIR + ":/work:ro") + " -v " + quote(OUT_DIR + ":/work/out")
# Command-line overrides never reach a nested just, so every nested just that reaches an exercise-scoped recipe
# is passed the active exercise explicitly. Shell-quoted here, so recipes interpolate EXERCISE_ARG unquoted.
EXERCISE_ARG := quote("EXERCISE=" + EXERCISE)
# The in-container runner; the only container path named outside MOUNTS.
VDEV_JUST := "just --justfile /work/vdev/justfile " + EXERCISE_ARG

[doc("verify the host tools the loop needs are on PATH")]
host-check:
  #!/usr/bin/env bash
  set -euo pipefail
  missing=()
  formulas=()
  for pair in just:just podman:podman qemu-system-aarch64:qemu; do
    tool="${pair%%:*}"
    command -v "${tool}" >/dev/null || { missing+=("${tool}"); formulas+=("${pair#*:}"); }
  done
  if (( ${#missing[@]} > 0 )); then
    printf 'missing host tools: %s\n' "${missing[*]}" >&2
    printf 'brew install %s\n' "${formulas[*]}" >&2
    exit 1
  fi

[doc("create the podman virtual dev machine if absent, start it if stopped, print its state")]
machine-vdev: host-check
  #!/usr/bin/env bash
  set -euo pipefail
  if ! podman machine inspect "{{MACHINE}}" >/dev/null 2>&1; then
    podman machine init --cpus "{{MACHINE_CPUS}}" --memory "{{MACHINE_MEMORY_MIB}}" --disk-size "{{MACHINE_DISK_GB}}" "{{MACHINE}}"
  fi
  if [[ "$(podman machine inspect --format '{{{{.State}}' "{{MACHINE}}")" != "running" ]]; then
    podman machine start "{{MACHINE}}"
  fi
  podman machine inspect --format '{{{{.Name}}: {{{{.State}}' "{{MACHINE}}" >&2

[doc("stop the podman virtual dev machine if it is running")]
machine-stop-vdev:
  #!/usr/bin/env bash
  set -euo pipefail
  if [[ "$(podman machine inspect --format '{{{{.State}}' "{{MACHINE}}" 2>/dev/null)" == "running" ]]; then
    podman machine stop "{{MACHINE}}"
  fi

[doc("build the kernel toolchain image from the Containerfile")]
image-vdev: machine-vdev
  #!/usr/bin/env bash
  set -euo pipefail
  podman build --tag "{{IMAGE}}" - < "{{justfile_directory()}}/Containerfile"

# Fails unless the machine is already running; never starts it.
[private]
guard-vdev:
  #!/usr/bin/env bash
  set -euo pipefail
  command -v podman >/dev/null || { printf 'podman not on PATH (%s)\n' "${PATH}" >&2; exit 1; }
  if ! state="$(podman machine inspect --format '{{{{.State}}' "{{MACHINE}}" 2>&1)"; then
    printf 'podman machine inspect failed as %s (HOME=%s): %s\n' "$(id -un)" "${HOME}" "${state}" >&2
    exit 1
  fi
  if [[ "${state}" != "running" ]]; then
    printf "dev box is not running (%s): run 'just machine-vdev'\n" "${state}" >&2
    exit 1
  fi

[doc("run a command in a fresh build container (machine must be running), e.g. just run-vdev ls /kernel")]
run-vdev +ARGS: guard-vdev
  #!/usr/bin/env bash
  set -euo pipefail
  mkdir -p "{{OUT_DIR}}"
  podman run --rm --workdir /kernel {{MOUNTS}} "{{IMAGE}}" "$@"

[doc("open an interactive bash shell in a fresh build container (machine must be running)")]
shell-vdev: guard-vdev
  #!/usr/bin/env bash
  set -euo pipefail
  mkdir -p "{{OUT_DIR}}"
  podman run --rm -it --workdir /kernel {{MOUNTS}} "{{IMAGE}}" bash

# Workflow entry points: start the machine, then hand the work to vdev/justfile.

[doc("download, verify and extract the pinned kernel source into the volume (no-op if present)")]
kernel-fetch-vdev: machine-vdev
  just run-vdev {{VDEV_JUST}} kernel-fetch

[doc("configure the kernel: defconfig, debug.config, then the vdev/kernel-config/ fragments")]
kernel-config-vdev: machine-vdev
  just run-vdev {{VDEV_JUST}} kernel-config

[doc("build the kernel Image and in-tree modules, and copy the Image to out/Image")]
kernel-build-vdev: machine-vdev
  just run-vdev {{VDEV_JUST}} kernel-build
  ls -l "{{OUT_DIR}}/Image"

[doc("make clean in the kernel tree (keeps .config); no-op if the tree is absent")]
kernel-clean-vdev: machine-vdev
  just run-vdev {{VDEV_JUST}} kernel-clean

[doc("stage a busybox root with vdev/initramfs/init, the out/driver/ modules, the out/userspace/ programs, libraries, scripts and public headers, and luajit, then pack it to out/initramfs.cpio.gz")]
initramfs-vdev: machine-vdev
  just run-vdev {{VDEV_JUST}} initramfs
  ls -l "{{OUT_DIR}}/initramfs.cpio.gz"

[doc("build the active exercise's out-of-tree module, exercises/EXERCISE/driver/, against the kernel tree; .ko files land in out/driver/")]
driver-vdev: machine-vdev
  just run-vdev {{VDEV_JUST}} driver
  ls -l "{{OUT_DIR}}/driver/"

[doc("remove out/driver-build/ (the MO= build trees) and out/driver/ for every exercise, not only the active one")]
driver-clean-vdev: machine-vdev
  just run-vdev {{VDEV_JUST}} driver-clean

[doc("run the API generator's unit tests on the dev box (see vdev/justfile api-gen-test)")]
api-gen-test-vdev: machine-vdev
  just run-vdev {{VDEV_JUST}} api-gen-test

[doc("generate the active exercise's userspace API artifacts on the dev box (see vdev/justfile generate)")]
generate-vdev: machine-vdev
  just run-vdev {{VDEV_JUST}} generate

[doc("build the active exercise's userspace, exercises/EXERCISE/userspace/, with clang (lib/ then app/); executables, lib*.so, script/* and the generated header and binding land in out/userspace/")]
userspace-vdev: machine-vdev
  just run-vdev {{VDEV_JUST}} userspace

[doc("remove out/userspace-build/ (the intermediate trees) and out/userspace/ for every exercise, not only the active one")]
userspace-clean-vdev: machine-vdev
  just run-vdev {{VDEV_JUST}} userspace-clean

[doc("generate out/compile_commands.json on the dev box (see vdev/justfile compile-commands)")]
compile-commands-vdev: machine-vdev
  just run-vdev {{VDEV_JUST}} compile-commands

[doc("run the image's clangd over stdio for a host editor's LSP client, with out/compile_commands.json and host<->container path mapping; machine must be running; extra args go to clangd")]
clangd-vdev *ARGS: guard-vdev
  #!/usr/bin/env bash
  set -euo pipefail
  mkdir -p "{{OUT_DIR}}"
  exec podman run --rm -i --workdir /work {{MOUNTS}} "{{IMAGE}}" clangd --compile-commands-dir=/work/out "--path-mappings={{REPO_DIR}}=/work" "$@"

[doc("run the kernel tree's checkpatch.pl over the active exercise's exercises/EXERCISE/driver/; fails on any error or warning")]
checkpatch-vdev: machine-vdev
  just run-vdev {{VDEV_JUST}} checkpatch

[doc("copy the kernel's .clang-format to out/clang-format (no-op if present)")]
export-clang-format-vdev *ARGS: machine-vdev
  @[[ -f "{{OUT_DIR}}/clang-format" ]] || just run-vdev {{VDEV_JUST}} export-clang-format "$@"

[doc("Rewrite IN PLACE every *.c and *.h under the active exercise's ./exercises/EXERCISE/driver/ with clang-format and the kernel tree's .clang-format")]
format: export-clang-format-vdev
  #!/usr/bin/env bash
  set -euo pipefail
  driver="./exercises/{{EXERCISE}}/driver"
  [[ -d "${driver}" ]] || { printf "exercise '%s' not found under ./exercises\n" "{{EXERCISE}}" >&2; exit 1; }
  find "${driver}" -type f \( -iname '*.h' -o -iname '*.c' \) | xargs clang-format -i --style="file:{{OUT_DIR}}/clang-format"
  printf 'formatted every driver c source under %s/\n' "${driver}"

# Test machine: boots out/ on the host under QEMU. run-vtarget and test-vtarget share vtarget-qemu.

# The one QEMU invocation: guards the inputs, then execs QEMU with APPEND as the kernel command line.
[private]
vtarget-qemu APPEND:
  #!/usr/bin/env bash
  set -euo pipefail
  [[ -f "{{OUT_DIR}}/Image" ]] || { printf "out/Image missing: run 'just kernel-build-vdev'\n" >&2; exit 1; }
  [[ -f "{{OUT_DIR}}/initramfs.cpio.gz" ]] || { printf "out/initramfs.cpio.gz missing: run 'just initramfs-vdev'\n" >&2; exit 1; }
  # VTARGET_DEVICES is space-separated, so recipes interpolate it unquoted here: word-splitting is the point.
  DEVICES=({{VTARGET_DEVICES}})
  DEVICE_ARGS=()
  for dev in ${DEVICES[@]+"${DEVICES[@]}"}; do
    DEVICE_ARGS+=(-device "${dev}")
  done
  exec qemu-system-aarch64 -M virt -accel hvf -cpu host \
    -smp "{{VTARGET_CPUS}}" -m "{{VTARGET_MEMORY}}" -nographic \
    ${DEVICE_ARGS[@]+"${DEVICE_ARGS[@]}"} \
    -kernel "{{OUT_DIR}}/Image" -initrd "{{OUT_DIR}}/initramfs.cpio.gz" \
    -append "${1}" -no-reboot

[private]
run-test-vtarget:
  #!/usr/bin/env bash
  set -euo pipefail
  # the sed range shows only the window from userspace up to the verdict line; the full console is in the log
  {{VTARGET_QEMU}} "{{VTARGET_APPEND}} lkds_test" < /dev/null 2>&1 | tee "{{VTARGET_TEST_LOG}}" || true
  if grep -qw 'lkds-test: exit 0' "{{VTARGET_TEST_LOG}}"; then
    exit 0
  fi
  exit 1

[doc("boot out/Image with out/initramfs.cpio.gz headless under qemu on the serial console (exit: Ctrl-A X); VTARGET_DEVICES is overridable on the command line, so `just VTARGET_DEVICES=\"\" run-vtarget` boots without any device")]
run-vtarget: host-check
  exec {{VTARGET_QEMU}} "{{VTARGET_APPEND}}"

[doc("boot with lkds_test on the kernel command line: the guest runs lkds-test and powers off; console echoed and saved to out/vtarget-test.log; passes only if the guest reports 'lkds-test: exit 0'; Ctrl-C stops a hung guest")]
test-vtarget: host-check
  #!/usr/bin/env bash
  set -euo pipefail
  #just run-test-vtarget | sed -n '/^lkds: userspace reached/,/^lkds-test: exit/p'
  stdbuf -oL -eL just run-test-vtarget 2>&1 | awk '
      /^lkds-test: exit / { print $0; exit(0); }
      /^lkds: userspace reached/ { p = 1; print ""; }
      p || /error|Error|warning/  { print; next; }
      { d = d + 1; if (d == 80) { printf ".\n"; d = 0; } else { printf "." } fflush(); }
      END { if (!p) print "" }'
  printf 'log: %s\n' "{{VTARGET_TEST_LOG}}"

[doc("format module sources and check for kernel coding standard compliance")]
precommit: format checkpatch-vdev

[doc("build the active exercise's modules and userspace, then the initramfs, in vdev")]
stage-vdev: machine-vdev
  just run-vdev {{VDEV_JUST}} stage

[doc("one dev iteration: build the active exercise's modules and userspace and the initramfs in vdev, then boot vtarget and run lkds-test")]
test: machine-vdev
  @just {{EXERCISE_ARG}} stage-vdev
  just test-vtarget

[doc("install or update the agent and command set under .claude/")]
agents:
	@mkdir -p "{{parent_directory(AGENTS_DIR)}}"
	@[[ -d "{{AGENTS_DIR}}" ]] && git -C "{{AGENTS_DIR}}" pull || git -C {{parent_directory(AGENTS_DIR)}} clone "{{AGENTS_REPO}}"
	just --justfile "{{AGENTS_DIR}}/justfile" install "$(pwd)"
