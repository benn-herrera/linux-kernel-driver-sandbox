set positional-arguments

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
DRIVERS_DIR := justfile_directory() / "drivers"
USERSPACE_DIR := justfile_directory() / "userspace"
OUT_DIR := justfile_directory() / "out"
VDEV_DIR := justfile_directory() / "vdev"
VTARGET_CPUS := "4"
VTARGET_MEMORY := "2G"
VTARGET_DEVICES := "edu,dma_mask=0xffffffff"
# Each mount is shell-quoted here, so recipes interpolate MOUNTS unquoted.
MOUNTS := "-v " + quote(KERNEL_VOLUME + ":/kernel") + " -v " + quote(DRIVERS_DIR + ":/work/drivers:ro") + " -v " + quote(USERSPACE_DIR + ":/work/userspace:ro") + " -v " + quote(OUT_DIR + ":/work/out") + " -v " + quote(VDEV_DIR + ":/work/vdev:ro")
# The in-container runner; the only container path named outside MOUNTS.
VDEV_JUST := "just --justfile /work/vdev/justfile"

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
  if [[ "$(podman machine inspect --format '{{{{.State}}' "{{MACHINE}}" 2>/dev/null)" != "running" ]]; then
    printf "dev box is not running: run 'just machine-vdev'\n" >&2
    exit 1
  fi

[doc("run a command in a fresh build container (machine must be running), e.g. just run-vdev ls /kernel")]
run-vdev +ARGS: guard-vdev
  #!/usr/bin/env bash
  set -euo pipefail
  mkdir -p "{{DRIVERS_DIR}}" "{{USERSPACE_DIR}}" "{{OUT_DIR}}"
  podman run --rm --workdir /kernel {{MOUNTS}} "{{IMAGE}}" "$@"

[doc("open an interactive bash shell in a fresh build container (machine must be running)")]
shell-vdev: guard-vdev
  #!/usr/bin/env bash
  set -euo pipefail
  mkdir -p "{{DRIVERS_DIR}}" "{{USERSPACE_DIR}}" "{{OUT_DIR}}"
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

[doc("stage a busybox root with vdev/initramfs/init and pack it to out/initramfs.cpio.gz")]
initramfs-vdev: machine-vdev
  just run-vdev {{VDEV_JUST}} initramfs
  ls -l "{{OUT_DIR}}/initramfs.cpio.gz"

[doc("build every out-of-tree module under drivers/ against the kernel tree; .ko files land in out/modules/")]
modules-vdev: machine-vdev
  just run-vdev {{VDEV_JUST}} modules
  ls -l "{{OUT_DIR}}/modules/"

[doc("remove out/modules-build/ (the MO= build trees) and out/modules/")]
modules-clean-vdev: machine-vdev
  just run-vdev {{VDEV_JUST}} modules-clean

[doc("build every program under userspace/ as a static binary with clang; binaries land in out/userspace/")]
userspace-vdev: machine-vdev
  just run-vdev {{VDEV_JUST}} userspace
  ls -l "{{OUT_DIR}}/userspace/"

[doc("remove out/userspace-build/ (the intermediate trees) and out/userspace/")]
userspace-clean-vdev: machine-vdev
  just run-vdev {{VDEV_JUST}} userspace-clean

[doc("run the kernel tree's checkpatch.pl over drivers/ (or one driver dir by name); fails on any error or warning")]
checkpatch-vdev *ARGS: machine-vdev
  just run-vdev {{VDEV_JUST}} checkpatch "$@"

[doc("copy the kernel's .clang-format to out/clang-format (no-op if present)")]
export-clang-format-vdev *ARGS: machine-vdev
  @[[ -f "{{OUT_DIR}}/clang-format" ]] || just run-vdev {{VDEV_JUST}} export-clang-format "$@"

[doc("Rewrite IN PLACE every *.c and *.h under ./drivers/*/ and ./userspace/*/ with clang-format and the kernel tree's .clang-format")]
format: export-clang-format-vdev
  #!/usr/bin/env bash
  set -euo pipefail
  find ./drivers ./userspace -type f \( -iname '*.h' -o -iname '*.c' \) | xargs clang-format -i --style="file:{{OUT_DIR}}/clang-format"
  echo "formatted all drivers and userspace c sources"

# Test machine: boots out/ on the host under QEMU.

[doc("boot out/Image with out/initramfs.cpio.gz headless under qemu on the serial console (exit: Ctrl-A X); VTARGET_DEVICES is overridable on the command line, so `just VTARGET_DEVICES=\"\" run-vtarget` boots without any device")]
run-vtarget: host-check
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
    -append 'console=ttyAMA0 earlycon panic=1' -no-reboot

[doc("install or update the agent and command set under .claude/")]
agents:
	@mkdir -p "{{parent_directory(AGENTS_DIR)}}"
	@[[ -d "{{AGENTS_DIR}}" ]] && git -C "{{AGENTS_DIR}}" pull || git -C {{parent_directory(AGENTS_DIR)}} clone "{{AGENTS_REPO}}"
	just --justfile "{{AGENTS_DIR}}/justfile" install "$(pwd)"
