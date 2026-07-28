from datetime import datetime, timezone
import asyncio
from uuid import uuid4

import pytest

from agent_dashboard.models import AgentEvent, AgentState, AgentStatus, Snapshot, TmuxLocation
from agent_dashboard.tui import ConversationScreen, DashboardApp, DashboardClient


class FakeClient:
    def __init__(self):
        self.agent = AgentState(
            agent_id="agent-1", session_id="session-1", status="working",
            last_event_type="started", last_event_at=datetime.now(timezone.utc),
            host_id="host-1", working_dir="/tmp/project", harness="pi",
            model="gpt-test", effort="high", location=TmuxLocation(pane="%1"),
        )
        self.seen_calls = []
        self.archive_calls = []
        self.focus_calls = []

    async def snapshot(self):
        return Snapshot(agents=[self.agent])

    async def events(self, agent_id):
        return [AgentEvent(
            event_id=uuid4(), agent_id=agent_id, session_id="session-1",
            event_type="message", timestamp=datetime.now(timezone.utc),
            host_id="host-1", working_dir="/tmp/project", harness="pi",
            location=TmuxLocation(pane="%1"), model="gpt-test", effort="high",
            message_role="assistant", message="Finished the task.",
        )]

    async def search_messages(self, query):
        return ["agent-1"] if "finished" in query.casefold() else []

    async def updates(self):
        self.agent = self.agent.model_copy(update={
            "status": AgentStatus.WAITING_FOR_INPUT,
            "last_event_type": "waiting_for_input",
            "last_event_at": datetime.now(timezone.utc),
            "unseen": True,
        })
        yield {"agent": self.agent.model_dump(mode="json")}
        await asyncio.Event().wait()

    async def set_seen(self, agent_id, seen):
        self.seen_calls.append((agent_id, seen))
        self.agent = self.agent.model_copy(update={"unseen": not seen})
        return self.agent

    async def set_archived(self, agent_id, archived):
        self.archive_calls.append((agent_id, archived))
        self.agent = self.agent.model_copy(update={"archived": archived})
        return self.agent

    async def mark_all_seen(self):
        self.agent = self.agent.model_copy(update={"unseen": False})
        return Snapshot(agents=[self.agent])

    async def focus(self, agent_id):
        self.focus_calls.append(agent_id)


class MultiAgentClient(FakeClient):
    async def snapshot(self):
        agents = []
        for index in range(3):
            agents.append(self.agent.model_copy(update={
                "agent_id": f"agent-{index + 1}",
                "session_id": f"session-{index + 1}",
                "last_event_at": datetime(2026, 1, index + 1, tzinfo=timezone.utc),
            }))
        return Snapshot(agents=agents)

    async def updates(self):
        await asyncio.Event().wait()
        yield


def test_tui_client_preserves_server_url_path_prefix():
    client = DashboardClient("https://example.test/agent-dashboard")
    assert str(__import__("httpx").URL(client.base_url).join("api/v1/agents")) == (
        "https://example.test/agent-dashboard/api/v1/agents"
    )


@pytest.mark.asyncio
async def test_tui_renders_compact_agent_snapshot_and_live_state():
    app = DashboardApp(client=FakeClient())
    assert app.theme == "nord"
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        table = app.query_one("#agents")
        assert str(table.get_cell_at((0, 0))) == "! >"
        assert str(table.get_cell_at((0, 1))) == "/tmp/project"
        assert str(table.get_cell_at((0, 2))) == "gpt-test · high"
        assert app.agents["agent-1"].status.value == "waiting_for_input"


@pytest.mark.asyncio
async def test_tui_separates_unseen_and_seen_rows_and_skips_divider():
    client = MultiAgentClient()
    client.agent = client.agent.model_copy(update={"unseen": False})
    app = DashboardApp(client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.agents["agent-3"] = app.agents["agent-3"].model_copy(update={"unseen": True})
        app.refresh_agents()
        table = app.query_one("#agents")

        assert app.row_agent_ids == ["agent-3", None, "agent-2", "agent-1"]
        assert "SEEN" in str(table.get_cell_at((1, 0)))
        assert app.selected_agent_id == "agent-3"

        await pilot.press("j")
        assert app.selected_agent_id == "agent-2"
        await pilot.press("k")
        assert app.selected_agent_id == "agent-3"


@pytest.mark.asyncio
async def test_enter_opens_conversation_and_escape_returns_to_list():
    app = DashboardApp(client=FakeClient())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, ConversationScreen)
        assert app.query_one("#messages") is not None
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, ConversationScreen)


@pytest.mark.asyncio
async def test_tui_keyboard_actions_toggle_seen_archive_and_focus():
    client = FakeClient()
    app = DashboardApp(client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()  # receive unseen live update
        await pilot.press("S")
        await pilot.pause()
        assert client.seen_calls == [("agent-1", True)]

        await pilot.press("F")
        await pilot.pause()
        assert client.focus_calls == ["agent-1"]

        await pilot.press("A")
        await pilot.pause()
        assert client.archive_calls == [("agent-1", True)]
        assert app.ordered_agent_ids == []
        await pilot.press("X")
        await pilot.pause()
        assert app.ordered_agent_ids == ["agent-1"]


@pytest.mark.asyncio
async def test_tui_supports_vim_style_list_navigation():
    app = DashboardApp(client=MultiAgentClient())
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.selected_agent_id == "agent-3"  # newest sorts first
        await pilot.press("j")
        assert app.selected_agent_id == "agent-2"
        await pilot.press("k")
        assert app.selected_agent_id == "agent-3"
        await pilot.press("G")
        assert app.selected_agent_id == "agent-1"
        await pilot.press("g")
        assert app.selected_agent_id == "agent-3"


@pytest.mark.asyncio
async def test_tui_slash_search_filters_incrementally_and_escape_clears():
    app = DashboardApp(client=MultiAgentClient())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("/")
        search = app.query_one("#search")
        assert search.display is True
        assert search.has_focus
        await pilot.press("a", "g", "e", "n", "t", "-", "2")
        await pilot.pause()
        assert app.ordered_agent_ids == ["agent-2"]
        await pilot.press("escape")
        await pilot.pause()
        assert search.display is False
        assert app.ordered_agent_ids == ["agent-3", "agent-2", "agent-1"]


@pytest.mark.asyncio
async def test_tui_search_includes_bm25_message_matches():
    app = DashboardApp(client=FakeClient())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("/")
        await pilot.press("f", "i", "n", "i", "s", "h", "e", "d")
        await pilot.pause()
        await pilot.pause()
        assert app.ordered_agent_ids == ["agent-1"]


@pytest.mark.asyncio
async def test_tui_ignores_late_refresh_after_session_list_unmounts():
    app = DashboardApp(client=MultiAgentClient())
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.query_one("#agents").remove()
        app.refresh_agents()  # A late SSE event during shutdown must be harmless.
