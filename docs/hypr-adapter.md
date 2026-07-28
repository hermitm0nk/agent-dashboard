# Hyprland window adapter

The workstation helper uses Hyprland only to focus terminal windows used by
tmux. It queries the compositor when a focus action is requested rather than
maintaining a window cache.

The combined dashboard server must run as the same Unix user and in the same
graphical session as Hyprland. It needs:

- `hyprctl` on `PATH`;
- `HYPRLAND_INSTANCE_SIGNATURE` and `XDG_RUNTIME_DIR` from the Hyprland session;
- access to the user's tmux processes and `/proc`;
- the session environment needed to start `foot`.

Commands are invoked with subprocess argument arrays, never through a shell.
Server-provided values are validated before being passed to tmux, SSH, foot, or
Hyprland.

## Hyprland operations

| Purpose | Command |
| --- | --- |
| Discover current windows | `hyprctl -j clients` |
| Read the focused window | `hyprctl -j activewindow` |
| Focus an exact window | `hyprctl dispatch focuswindow address:<address>` |

For each focus request, the adapter validates the JSON response, resolves the
matching foot window, focuses it, and verifies the active window address.
Only one focus workflow should run at a time per workstation server.

## tmux and foot

Hooks store a tmux pane identifier. They do not store a Hyprland address because
tmux sessions can outlive terminal windows.

For an attached local client, the helper selects the requested tmux window and
pane and finds the corresponding foot client. If no matching client exists, it
starts a foot window with a tmux attachment. For a remote agent it starts foot
with an SSH tmux connection, then focuses the new terminal after it appears in
Hyprland. Existing tagged foot windows are reused when possible.

The subprocess runner is injectable so malformed compositor output, missing
windows, timeouts, and failed focus verification can be tested without a live
Hyprland session.
