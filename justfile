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
OUT_DIR := justfile_directory() / "out"
# Each mount is shell-quoted here, so recipes interpolate MOUNTS unquoted.
MOUNTS := "-v " + quote(KERNEL_VOLUME + ":/kernel") + " -v " + quote(DRIVERS_DIR + ":/work/drivers") + " -v " + quote(OUT_DIR + ":/work/out")

[doc("Verify the host tools the loop needs are on PATH")]
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

[doc("Create the Podman machine if absent, start it if stopped, print its state")]
machine: host-check
  #!/usr/bin/env bash
  set -euo pipefail
  if ! podman machine inspect "{{MACHINE}}" >/dev/null 2>&1; then
    podman machine init --cpus "{{MACHINE_CPUS}}" --memory "{{MACHINE_MEMORY_MIB}}" --disk-size "{{MACHINE_DISK_GB}}" "{{MACHINE}}"
  fi
  if [[ "$(podman machine inspect --format '{{{{.State}}' "{{MACHINE}}")" != "running" ]]; then
    podman machine start "{{MACHINE}}"
  fi
  podman machine inspect --format '{{{{.Name}}: {{{{.State}}' "{{MACHINE}}" >&2

[doc("Stop the Podman machine if it is running")]
machine-stop:
  #!/usr/bin/env bash
  set -euo pipefail
  if [[ "$(podman machine inspect --format '{{{{.State}}' "{{MACHINE}}" 2>/dev/null)" == "running" ]]; then
    podman machine stop "{{MACHINE}}"
  fi

[doc("Build the kernel toolchain image from the Containerfile")]
image: machine
  #!/usr/bin/env bash
  set -euo pipefail
  podman build --tag "{{IMAGE}}" - < "{{justfile_directory()}}/Containerfile"

[doc("Run a command in a fresh build container, e.g. just run make -C /kernel/linux Image")]
run +ARGS: machine
  #!/usr/bin/env bash
  set -euo pipefail
  mkdir -p "{{DRIVERS_DIR}}" "{{OUT_DIR}}"
  podman run --rm --workdir /kernel {{MOUNTS}} "{{IMAGE}}" "$@"

[doc("Open an interactive bash shell in a fresh build container")]
shell: machine
  #!/usr/bin/env bash
  set -euo pipefail
  mkdir -p "{{DRIVERS_DIR}}" "{{OUT_DIR}}"
  podman run --rm -it --workdir /kernel {{MOUNTS}} "{{IMAGE}}" bash

agents:
	@mkdir -p "{{parent_directory(AGENTS_DIR)}}"
	@[[ -d "{{AGENTS_DIR}}" ]] && git -C "{{AGENTS_DIR}}" pull || git -C {{parent_directory(AGENTS_DIR)}} clone "{{AGENTS_REPO}}"
	just --justfile "{{AGENTS_DIR}}/justfile" install "$(pwd)"
