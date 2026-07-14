from pathlib import Path

import pytest

from agent_dashboard.actions import FirefoxAdapter, HyprlandAdapter, SshAdapter, TmuxAdapter
from agent_dashboard.models import FirefoxLocation, TmuxLocation


@pytest.mark.asyncio
async def test_tmux_action_uses_argument_array_and_focuses_foot():
    calls = []
    focused = []

    async def runner(*args): calls.append(args)
    async def query(*_args): return "42\t/dev/pts/2\n"
    class Hypr:
        async def clients(self):
            return [{"address": "0x123", "pid": 99, "class": "foot", "title": "dev"}]
        async def focus(self, address): focused.append(address)
    adapter = TmuxAdapter("host-1", runner, Hypr(), query)
    adapter._ancestry = lambda _pid: {42, 99}
    await adapter.go_to(TmuxLocation(session="dev", window="1", pane="2"), origin_host="host-1",
                        agent_id="agent-1")
    assert calls == [("tmux", "switch-client", "-c", "/dev/pts/2", "-t", "dev:1.2")]
    assert focused == ["0x123"]


@pytest.mark.asyncio
async def test_hyprland_queries_focuses_and_verifies_exact_address():
    calls = []
    async def runner(*args):
        calls.append(args)
        if args[-1] == "clients":
            return '[{"address":"0xABC","pid":12,"class":"foot"}]'
        if args[-1] == "activewindow":
            return '{"address":"0xABC","pid":12,"class":"foot"}'
        return "ok"
    adapter = HyprlandAdapter(runner)
    assert (await adapter.clients())[0]["address"] == "0xABC"
    await adapter.focus("0xABC")
    await adapter.send_shortcut("0xABC", "ALT", "F12")
    assert calls[-1] == ("hyprctl", "dispatch", "sendshortcut", "ALT,F12,address:0xabc")


@pytest.mark.asyncio
async def test_hyprland_rejects_failed_focus_verification():
    async def runner(*args):
        if args[-1] == "activewindow":
            return '{"address":"0x999","pid":12,"class":"foot"}'
        return "ok"
    with pytest.raises(RuntimeError, match="did not focus"):
        await HyprlandAdapter(runner).focus("0x123")


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
    focused = []

    async def runner(*args): calls.append(args)
    class Hypr:
        async def clients(self):
            return [{"address": "0xf1", "pid": 1, "class": "firefox"}]
        async def focus(self, address): focused.append(address)
        async def send_shortcut(self, address, modifiers, key):
            calls.append(("shortcut", address, modifiers, key))
    adapter = FirefoxAdapter(tab_list, tab_command, runner, hyprland=Hypr())
    location = FirefoxLocation(window_tab="2.3", url="https://example.test/", title="Dashboard")
    await adapter.go_to(location)
    assert tab_command.read_text() == "2.3\n"
    assert focused == ["0xf1"]
    assert calls == [("shortcut", "0xf1", "ALT", "F12")]


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
