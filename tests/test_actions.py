from pathlib import Path

import pytest

from agent_dashboard.actions import FirefoxAdapter, SshAdapter, TmuxAdapter
from agent_dashboard.models import FirefoxLocation, TmuxLocation


@pytest.mark.asyncio
async def test_tmux_action_uses_argument_array_and_focuses_foot():
    calls = []

    async def runner(*args): calls.append(args)
    adapter = TmuxAdapter("host-1", runner)
    await adapter.go_to(TmuxLocation(session="dev", window="1", pane="2"), origin_host="host-1",
                        agent_id="agent-1", client_tty="/dev/pts/2", foot_address="0x123")
    assert calls == [("tmux", "switch-client", "-c", "/dev/pts/2", "-t", "dev:1.2"),
                     ("hyprctl", "dispatch", "focuswindow", "address:0x123")]


@pytest.mark.asyncio
async def test_ssh_adapter_rejects_shell_injection():
    adapter = SshAdapter(lambda *_: None)
    with pytest.raises(ValueError):
        await adapter.open_tmux("host;rm", "dev", "agent-1")


@pytest.mark.asyncio
async def test_firefox_prefers_window_tab_id_and_writes_atomically(tmp_path: Path):
    tab_list, tab_command = tmp_path / "tab-list", tmp_path / "tab-command"
    tab_list.write_text("2.3\tDashboard\thttps://example.test/\n")
    calls = []

    async def runner(*args): calls.append(args)
    adapter = FirefoxAdapter(tab_list, tab_command, runner)
    location = FirefoxLocation(window_tab="2.3", url="https://example.test/", title="Dashboard")
    await adapter.go_to(location)
    assert tab_command.read_text() == "2.3\n"
    assert calls == [("wtype", "-M", "alt", "-k", "F12", "-m", "alt")]


@pytest.mark.asyncio
async def test_firefox_opens_only_http_urls_when_tab_missing(tmp_path: Path):
    calls = []
    async def runner(*args): calls.append(args)
    adapter = FirefoxAdapter(tmp_path / "tabs", tmp_path / "command", runner)
    await adapter.go_to(FirefoxLocation(window_tab="1.1", url="https://example.test/new", title="New"))
    assert calls == [("firefox", "--new-window", "https://example.test/new")]
