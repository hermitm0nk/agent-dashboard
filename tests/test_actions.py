import pytest

from agent_dashboard.actions import HyprlandAdapter, SshAdapter, TmuxAdapter
from agent_dashboard.models import TmuxLocation


@pytest.mark.asyncio
async def test_tmux_action_uses_argument_array_and_focuses_foot():
    calls = []
    focused = []

    async def runner(*args): calls.append(args)
    async def query(*args):
        return "$0\ttmux:$0.@1.%2\n"
    class Hypr:
        async def clients(self):
            return [{"address": "0x123", "pid": 99, "class": "foot", "title": "agents/zsh tmux:$0.@9.%8"}]
        async def focus(self, address): focused.append(address)
    adapter = TmuxAdapter("host-1", runner, Hypr(), query)
    await adapter.go_to(TmuxLocation(pane="%2"), origin_host="host-1",
                        agent_id="agent-1")
    assert calls == [("tmux", "select-window", "-t", "%2"),
                     ("tmux", "select-pane", "-t", "%2")]
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
    assert calls[-1] == ("hyprctl", "-j", "activewindow")


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
    location = TmuxLocation(pane="%2")
    async def query(*args):
        return "$0\ttmux:$0.@1.%2"
    await TmuxAdapter("local", runner, query_runner=query).go_to(
        location, origin_host="local", agent_id="agent-1")
    assert calls[:2] == [("tmux", "select-window", "-t", "%2"),
                         ("tmux", "select-pane", "-t", "%2")]


@pytest.mark.asyncio
async def test_tmux_opens_foot_when_no_matching_window_exists():
    calls = []
    focused = []
    async def runner(*args): calls.append(args)
    async def query(*args):
        return "$0\ttmux:$0.@1.%2"
    class Hypr:
        async def clients(self): return []
        async def wait_for_client(self, predicate):
            client = {"address": "0x456", "pid": 10, "class": "foot", "title": "tmux:$0.@1.%2"}
            assert predicate(client)
            return client
        async def focus(self, address): focused.append(address)
    await TmuxAdapter("local", runner, Hypr(), query).go_to(
        TmuxLocation(pane="%2"), origin_host="local", agent_id="agent-1")
    assert calls[-1] == ("foot", "--title=tmux:$0.@1.%2", "tmux", "attach-session", "-t", "%2")
    assert focused == ["0x456"]


@pytest.mark.asyncio
async def test_tmux_pane_id_is_used_as_the_target():
    calls = []
    async def runner(*args): calls.append(args)
    async def query(*args): return "$0\ttmux:$0.@1.%2"
    await TmuxAdapter("local", runner, query_runner=query).go_to(
        TmuxLocation(pane="%7"), origin_host="local", agent_id="agent-1")
    assert calls[:2] == [("tmux", "select-window", "-t", "%7"),
                         ("tmux", "select-pane", "-t", "%7")]
