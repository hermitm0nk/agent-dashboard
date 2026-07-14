import asyncio
import os
import re
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from urllib.parse import urlparse

from .models import FirefoxLocation, TmuxLocation

Runner = Callable[..., Awaitable[None]]
IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]+$")
HOST = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_.:-]*[A-Za-z0-9])?$")


def _check(value: str, pattern: re.Pattern[str], label: str) -> str:
    if not pattern.fullmatch(value):
        raise ValueError(f"invalid {label}")
    return value


async def _exec(*args: str):
    process = await asyncio.create_subprocess_exec(*args)
    if await process.wait():
        raise RuntimeError(f"{args[0]} exited with {process.returncode}")


class TmuxAdapter:
    def __init__(self, helper_host: str, runner: Runner | None = None):
        self.helper_host, self.runner = helper_host, runner or _exec

    async def go_to(self, location: TmuxLocation, *, origin_host: str, agent_id: str,
                    client_tty: str | None = None, foot_address: str | None = None):
        for value, label in ((location.session, "session"), (location.window, "window"), (location.pane, "pane")):
            _check(value, IDENTIFIER, label)
        _check(agent_id, IDENTIFIER, "agent id")
        target = f"{location.session}:{location.window}.{location.pane}"
        if origin_host != self.helper_host:
            _check(origin_host, HOST, "host")
            await self.runner("foot", f"--title=agent-dashboard:{agent_id}", "ssh", "-t", origin_host,
                              "tmux", "attach-session", "-t", target)
        elif client_tty:
            await self.runner("tmux", "switch-client", "-c", client_tty, "-t", target)
        else:
            await self.runner("foot", f"--title=agent-dashboard:{agent_id}", "tmux", "attach-session",
                              "-t", target)
        if foot_address:
            await self.runner("hyprctl", "dispatch", "focuswindow", f"address:{foot_address}")


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
                 helper_host: str | None = None):
        self.tab_list, self.tab_command, self.runner = Path(tab_list), Path(tab_command), runner or _exec
        self.helper_host = helper_host

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

    async def go_to(self, location: FirefoxLocation, *, firefox_address: str | None = None,
                    origin_host: str | None = None):
        parsed = urlparse(str(location.url))
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Firefox location must use an http or https URL")
        tab_id = None if self.helper_host and origin_host and origin_host != self.helper_host else self._find_tab(location)
        if tab_id:
            self._write_command(tab_id)
            if firefox_address:
                await self.runner("hyprctl", "dispatch", "focuswindow", f"address:{firefox_address}")
            await self.runner("wtype", "-M", "alt", "-k", "F12", "-m", "alt")
        else:
            await self.runner("firefox", "--new-window", str(location.url))
