import asyncio
import json
import os
import re
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from urllib.parse import urlparse

from .models import FirefoxLocation, TmuxLocation

Runner = Callable[..., Awaitable[object]]
IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:$@%-]+$")
HOST = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_.:-]*[A-Za-z0-9])?$")
ADDRESS = re.compile(r"^0x[0-9a-fA-F]+$")


def _check(value: str, pattern: re.Pattern[str], label: str) -> str:
    if not pattern.fullmatch(value):
        raise ValueError(f"invalid {label}")
    return value


async def _exec(*args: str):
    process = await asyncio.create_subprocess_exec(*args)
    if await process.wait():
        raise RuntimeError(f"{args[0]} exited with {process.returncode}")


async def _capture(*args: str) -> str:
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    if process.returncode:
        message = stderr.decode(errors="replace").strip()
        raise RuntimeError(f"{args[0]} exited with {process.returncode}: {message}")
    return stdout.decode()


class HyprlandAdapter:
    """Stateless, on-demand access to the current Hyprland window inventory."""

    def __init__(self, runner: Runner | None = None, *, poll_interval: float = 0.05):
        self.runner = runner or _capture
        self.poll_interval = poll_interval
        self._focus_lock = asyncio.Lock()

    async def _json(self, command: str) -> object:
        raw = await self.runner("hyprctl", "-j", command)
        if isinstance(raw, bytes):
            raw = raw.decode()
        if not isinstance(raw, str):
            raise RuntimeError(f"hyprctl {command} returned no output")
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise RuntimeError(f"hyprctl {command} returned invalid JSON") from exc

    @staticmethod
    def _client(value: object) -> dict:
        if not isinstance(value, dict) or not ADDRESS.fullmatch(str(value.get("address", ""))):
            raise RuntimeError("hyprctl returned an invalid client")
        if not isinstance(value.get("pid"), int):
            raise RuntimeError("hyprctl returned a client without a PID")
        return value

    async def clients(self) -> list[dict]:
        values = await self._json("clients")
        if not isinstance(values, list):
            raise RuntimeError("hyprctl clients did not return a list")
        return [self._client(value) for value in values]

    async def active_window(self) -> dict | None:
        value = await self._json("activewindow")
        if value == {}:
            return None
        return self._client(value)

    @staticmethod
    def _address(address: str) -> str:
        return _check(address, ADDRESS, "Hyprland address").lower()

    async def focus(self, address: str):
        address = self._address(address)
        async with self._focus_lock:
            await self.runner("hyprctl", "dispatch", "focuswindow", f"address:{address}")
            active = await self.active_window()
            if active is None or str(active["address"]).lower() != address:
                raise RuntimeError("Hyprland did not focus the requested window")

    async def send_shortcut(self, address: str, modifiers: str, key: str):
        address = self._address(address)
        if not re.fullmatch(r"[A-Z_+]*", modifiers) or not re.fullmatch(r"[A-Za-z0-9_]+", key):
            raise ValueError("invalid shortcut")
        await self.runner("hyprctl", "dispatch", "sendshortcut",
                          f"{modifiers},{key},address:{address}")

    async def wait_for_client(self, predicate: Callable[[dict], bool], timeout: float = 2.0) -> dict:
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            matches = [client for client in await self.clients() if predicate(client)]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                raise RuntimeError("multiple Hyprland windows matched")
            if asyncio.get_running_loop().time() >= deadline:
                raise RuntimeError("timed out waiting for a Hyprland window")
            await asyncio.sleep(self.poll_interval)


class TmuxAdapter:
    def __init__(self, helper_host: str, runner: Runner | None = None,
                 hyprland: HyprlandAdapter | None = None, query_runner: Runner | None = None):
        self.helper_host, self.runner = helper_host, runner or _exec
        self.hyprland, self.query_runner = hyprland, query_runner or _capture

    async def _target_info(self, target: str) -> tuple[str, str]:
        raw = await self.query_runner("tmux", "display-message", "-p", "-t", target,
                                      "#{session_id}\ttmux:#{session_id}.#{window_id}.#{pane_id}")
        if isinstance(raw, bytes):
            raw = raw.decode()
        session, separator, marker = str(raw).strip().partition("\t")
        if not separator or not session or not marker:
            raise RuntimeError("tmux returned invalid target information")
        return session, marker

    async def go_to(self, location: TmuxLocation, *, origin_host: str, agent_id: str,
                    client_tty: str | None = None):
        _check(location.pane, IDENTIFIER, "pane")
        _check(agent_id, IDENTIFIER, "agent id")
        if origin_host != self.helper_host:
            raise ValueError("focus command was routed to the wrong workstation")
        target = location.pane
        session, marker = await self._target_info(target)
        session_marker = f"tmux:{session}."
        await self.runner("tmux", "select-window", "-t", target)
        await self.runner("tmux", "select-pane", "-t", target)
        foot = None
        if self.hyprland:
            foot = next((client for client in await self.hyprland.clients()
                         if str(client.get("class", "")).lower() == "foot"
                         and session_marker in str(client.get("title", ""))), None)
            if foot is None:
                await self.runner("foot", f"--title={marker}", "tmux", "attach-session", "-t", target)
                foot = await self.hyprland.wait_for_client(
                    lambda client: str(client.get("class", "")).lower() == "foot"
                    and session_marker in str(client.get("title", ""))
                )
            await self.hyprland.focus(foot["address"])


class SshAdapter:
    def __init__(self, runner: Runner | None = None):
        self.runner = runner or _exec

    async def open_tmux(self, host: str, session: str, agent_id: str):
        _check(host, HOST, "host")
        _check(session, IDENTIFIER, "session")
        _check(agent_id, IDENTIFIER, "agent id")
        await self.runner("foot", f"--title=agent-dashboard:{agent_id}", "ssh", "-t", host,
                          "tmux", "attach-session", "-t", session)


class FirefoxAdapter:
    def __init__(self, tab_list: str | Path = "/tmp/tridactyl-remote/tab-list",
                 tab_command: str | Path = "/tmp/tridactyl-remote/tab-command", runner: Runner | None = None,
                 helper_host: str | None = None, hyprland: HyprlandAdapter | None = None):
        self.tab_list, self.tab_command, self.runner = Path(tab_list), Path(tab_command), runner or _exec
        self.helper_host = helper_host
        self.hyprland = hyprland

    @staticmethod
    def _is_firefox(client: dict) -> bool:
        return "firefox" in str(client.get("class", "")).lower()

    async def _firefox(self) -> dict:
        assert self.hyprland is not None
        matches = [client for client in await self.hyprland.clients() if self._is_firefox(client)]
        if len(matches) == 1:
            return matches[0]
        if matches:
            active = await self.hyprland.active_window()
            if active and any(client["address"].lower() == active["address"].lower() for client in matches):
                return active
            raise RuntimeError("multiple Firefox windows are open")
        raise RuntimeError("no Firefox window is open")

    def _find_tab(self, location: FirefoxLocation) -> str | None:
        if not self.tab_list.exists():
            return None
        rows = []
        for line in self.tab_list.read_text().splitlines():
            parts = line.split("\t", 2)
            if len(parts) == 3:
                rows.append(parts)
        exact_id = next((row for row in rows if row[0] == location.window_tab), None)
        if exact_id:
            return exact_id[0]
        exact_url = [row for row in rows if row[2] == str(location.url)]
        if len(exact_url) > 1 and location.title:
            title_match = next((row for row in exact_url if row[1] == location.title), None)
            if title_match:
                return title_match[0]
        return exact_url[0][0] if exact_url else None

    def _write_command(self, tab_id: str):
        self.tab_command.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=self.tab_command.parent, prefix=".tab-command-")
        try:
            with os.fdopen(fd, "w") as stream:
                stream.write(tab_id + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.tab_command)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    async def go_to(self, location: FirefoxLocation, *, origin_host: str | None = None):
        parsed = urlparse(str(location.url))
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Firefox location must use an http or https URL")
        tab_id = None if self.helper_host and origin_host and origin_host != self.helper_host else self._find_tab(location)
        if tab_id:
            self._write_command(tab_id)
            if self.hyprland:
                firefox = await self._firefox()
                await self.hyprland.focus(firefox["address"])
                await self.hyprland.send_shortcut(firefox["address"], "ALT", "F12")
            else:
                raise RuntimeError("Firefox focus requires the Hyprland adapter")
        else:
            previous = ({client["address"].lower() for client in await self.hyprland.clients()
                         if self._is_firefox(client)} if self.hyprland else set())
            await self.runner("firefox", "--new-window", str(location.url))
            if self.hyprland:
                firefox = await self.hyprland.wait_for_client(
                    lambda client: self._is_firefox(client)
                    and client["address"].lower() not in previous
                )
                await self.hyprland.focus(firefox["address"])
