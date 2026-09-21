# CONVENTIONS – linux-kernel-driver-sandbox

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
- Podman machine sizing lives in the `MACHINE_*` variables in the justfile.
  Changing them does not resize an existing machine: remove it with
  `podman machine rm` and run `just machine` again. No target runs
  `podman machine set`.
