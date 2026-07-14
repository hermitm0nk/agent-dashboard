# Hyprland window adapter

This document is the reference design for the Hyprland integration. It describes
the behavior the workstation server should eventually implement; the feature is
not complete today.

The adapter is intentionally stateless. It queries Hyprland when a focus action
is requested instead of maintaining a window cache or subscribing to compositor
events.

## Current gap

`TmuxAdapter` and `FirefoxAdapter` can already execute:

```text
hyprctl dispatch focuswindow address:<address>
```

but only if a caller supplies the address. The workstation action service currently does
not discover a foot or Firefox address and does not pass one to either adapter.
The Hyprland adapter fills that gap.

## Requirements

The combined dashboard server must run as the same Unix user and in the same
graphical session as Hyprland. It should normally be a Hyprland-session
systemd user service. It needs:

- `hyprctl` on `PATH`;
- `HYPRLAND_INSTANCE_SIGNATURE` and `XDG_RUNTIME_DIR` from the Hyprland session;
- access to the user's tmux processes and `/proc` for terminal PID matching;
- access to the Tridactyl files under `/tmp/tridactyl-remote`; and
- the session environment needed to start `foot` and `firefox`.

The adapter must invoke commands with subprocess argument arrays, never through
a shell. It must not accept arbitrary commands, selectors, or regular
expressions from the dashboard server.

## Why only `hyprctl`

Hyprland exposes Unix-socket IPC, and `hyprctl` is its supported command-line
client. The adapter can perform every operation it needs through that CLI:

| Purpose | Command |
| --- | --- |
| Discover current windows | `hyprctl -j clients` |
| Read the focused window | `hyprctl -j activewindow` |
| Focus an exact window | `hyprctl dispatch focuswindow address:<address>` |
| Send the Tridactyl shortcut | `hyprctl dispatch sendshortcut ALT,F12,address:<address>` |

The exact `sendshortcut` argument syntax must be covered by an integration test
against the Hyprland version supported by the project. Hyprland documents it as
`mod, key[, window]` and supports an exact `address:0x...` window selector; see
the [dispatcher reference](https://wiki.hypr.land/0.54.0/Configuring/Dispatchers/).

There is no need to open either IPC socket directly. In particular, the event
socket would only be useful if the application needed a continuously updated
window model. Focus is an occasional user action, so querying `clients` at that
moment is simpler and gives the adapter the current authoritative state. It
also avoids cache invalidation, startup races, reconnection logic, and a
long-running background task.

The project should reconsider event tracking only if `hyprctl` query latency
becomes measurable or another feature needs live window updates.

## Adapter behavior

For each focus request, the adapter should:

1. Run `hyprctl -j clients`.
2. Validate and parse the JSON response.
3. Resolve the requested application to exactly one current window address.
4. Run `hyprctl dispatch focuswindow address:<address>`.
5. Run `hyprctl -j activewindow` and verify that its normalized address matches.
6. Return success only after verification.

If the address disappears between discovery and dispatch, query `clients` once
more and repeat resolution. Do not retry an old address: Hyprland addresses are
local, short-lived compositor identifiers.

Only one focus workflow should run at a time per workstation server. Serializing discovery,
application selection, focus, verification, and shortcut delivery prevents two
dashboard requests from interfering with one another.

## tmux and foot

Hooks store a tmux session, window, and pane. They deliberately do not store a
Hyprland address because tmux sessions can outlive terminal windows.

For a local agent with an attached client:

1. Use `tmux list-clients` to find a client attached to the recorded session and
   read its `client_pid` and `client_tty`.
2. Walk the client PID's process ancestry.
3. From the current `hyprctl -j clients` result, find the foot client whose PID
   appears in that ancestry.
4. Run `tmux switch-client -c <client_tty> -t
   <session>:<window>.<pane>`.
5. Focus and verify that foot window by its exact address.

If PID matching is unavailable, an exact configured title containing a unique
dashboard prefix and tmux session ID may be used as a fallback. Fuzzy title or
class matching is not safe when several terminals are open.

If no client is attached, start:

```text
foot --title=agent-dashboard:<agent-id> tmux attach-session -t <target>
```

For an agent on another host, start foot with `ssh -t <host> tmux
attach-session ...`. Poll `hyprctl -j clients` with a short timeout until the
new exact tagged foot window appears, then focus and verify it. Existing tagged
windows should be reused when possible.

## Firefox and Tridactyl

Tridactyl remains responsible for selecting the browser tab. The Firefox
adapter resolves the recorded `window.tab` ID from
`/tmp/tridactyl-remote/tab-list` and atomically writes it to `tab-command`.

It should then:

1. Query `hyprctl -j clients` and resolve the appropriate Firefox window.
2. Focus that exact address and verify it with `hyprctl -j activewindow`.
3. Send Alt+F12 to that window with `hyprctl dispatch sendshortcut`, replacing
   the current `wtype` call.

Targeting the address in `sendshortcut` keeps the action within Hyprland and
reduces the chance of sending input to the wrong application. Verification is
still required because focusing the correct top-level window is part of the
user-visible action, not merely a prerequisite for the shortcut.

If tab metadata cannot identify which native Firefox window owns a tab, several
Firefox windows are ambiguous. The implementation may prefer an already active
Firefox window or the only Firefox window, but it must return an explicit error
rather than choose arbitrarily when no safe deterministic match exists.

If the tab is absent, run `firefox --new-window <url>`. Record the Firefox
addresses seen before launch and poll `hyprctl -j clients` until a new one
appears, with a bounded timeout. Only `http` and `https` URLs are allowed.

## Integration shape

The server owns one lightweight workstation action service and injects its
`HyprlandAdapter` into `TmuxAdapter` and `FirefoxAdapter`:

```text
Dashboard server
  -> workstation action service
  -> HyprlandAdapter (query, resolve, focus, verify, send shortcut)
  -> TmuxAdapter      (switch or attach the tmux target)
  -> FirefoxAdapter   (select or open the browser tab)
```

The application adapters should request windows by semantic identity rather
than accept `foot_address` or `firefox_address` from their callers. Useful
Hyprland adapter operations include:

- `clients()`;
- `active_window()`;
- `focus(address)`;
- `send_shortcut(address, modifiers, key)`; and
- `wait_for_client(predicate, timeout)`.

For a remote agent, its workstation server connects outbound to the main server
over WebSocket, registers its host ID, and receives the same semantic focus
command over that connection. The remote server executes it locally; compositor
addresses never cross the network.

The subprocess runner should be injectable so resolution, invalid output,
address expiry, timeouts, and failed verification can be unit tested without a
running compositor.

## Completion criteria

The feature is complete when tests and a real Hyprland session demonstrate:

- exact foot resolution for a local attached tmux client;
- polling and focus for newly opened local and remote foot windows;
- Firefox window focus followed by a targeted Tridactyl shortcut;
- no dependency on `wtype` or direct Hyprland socket access;
- correct failures for malformed JSON, missing or ambiguous windows, timeouts,
  stale addresses, and failed active-window verification; and
- no path from server-provided values to a shell command or arbitrary Hyprland
  selector.
