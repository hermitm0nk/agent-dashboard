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
    with pytest.raises(ValueError):
        await adapter.open_tmux("-oProxyCommand=bad", "dev", "agent-1")


@pytest.mark.asyncio
async def test_tmux_attach_selects_the_full_target():
    calls = []
    async def runner(*args): calls.append(args)
    location = TmuxLocation(session="dev", window="1", pane="2")
    await TmuxAdapter("local", runner).go_to(location, origin_host="local", agent_id="agent-1")
    await TmuxAdapter("local", runner).go_to(location, origin_host="remote", agent_id="agent-1")
    assert calls[0][-2:] == ("-t", "dev:1.2")
    assert calls[1][-2:] == ("-t", "dev:1.2")


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


def test_firefox_uses_title_to_disambiguate_equal_urls(tmp_path: Path):
    tab_list = tmp_path / "tab-list"
    tab_list.write_text("1.1\tFirst\thttps://example.test/\n2.2\tWanted\thttps://example.test/\n")
    adapter = FirefoxAdapter(tab_list, tmp_path / "command")
    location = FirefoxLocation(window_tab="9.9", url="https://example.test/", title="Wanted")
    assert adapter._find_tab(location) == "2.2"
