# Claude Code Instructions

This repository is the control center that assembles every pack and runs everyone's tests, a sibling of dirigent in the same workspace, and follows dirigent's
instructions in full:

@../dirigent/CLAUDE.md

## Here

- A change that adds a pack, or makes a block or source reach an outside system the
  architecture model does not show yet, updates `architecture/workspace.dsl` in dirigent in a PR
  there, and regenerates its docs page with `make architecture-export-docs`.
- Run this repository's gates with `env -u VIRTUAL_ENV` when a dirigent venv is active.
