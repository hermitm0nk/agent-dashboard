# Implementation plan

This plan follows the implementation order in `README.md`. Each stage is
implemented with unit and end-to-end tests and committed separately.

## Stage 1 — shared server core

- [x] Define normalized event, location, and agent models.
- [x] Add SQLite migrations and persistence for current agents and event history.
- [x] Add versioned FastAPI event, snapshot, and SSE endpoints.
- [x] Add unit and end-to-end tests.
- [x] Run checks and commit the stage.

## Stage 2 — first harness and TUI

- [x] Add one harness hook.
- [x] Add the Textual TUI client.
- [x] Add unit and end-to-end tests.
- [x] Run checks and commit the stage.

## Stage 3 — Web UI and notification rules

- [x] Add the static Web UI.
- [x] Add notification rule evaluation.
- [x] Add unit and end-to-end tests.
- [x] Run checks and commit the stage.

## Stage 4 — notification delivery and workstation helper

- [x] Add ntfy and WebPush adapters.
- [x] Add the workstation helper and D-Bus adapter.
- [x] Add unit and end-to-end tests.
- [x] Run checks and commit the stage.

## Stage 5 — go-to adapters and remaining hooks

- [x] Add tmux, Firefox, and SSH action adapters.
- [x] Add the pi harness hook.
- [x] Add the remaining harness hooks.
- [x] Add unit and end-to-end tests.
- [x] Run checks and commit the stage.
