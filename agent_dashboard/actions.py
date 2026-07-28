import asyncio
import json
import os
import re
from collections.abc import Awaitable, Callable

from .models import TmuxLocation

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

    @staticmethod
    def _address(address: str) -> str:
        return _check(address, ADDRESS, "Hyprland address").lower()

    async def focus(self, address: str):
        address = self._address(address)
        async with self._focus_lock:
            await self.runner("hyprctl", "dispatch", "focuswindow", f"address:{address}")
            active_value = await self._json("activewindow")
            if not isinstance(active_value, dict) or str(active_value.get("address", "")).lower() != address:
                raise RuntimeError("Hyprland did not focus the requested window")

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
