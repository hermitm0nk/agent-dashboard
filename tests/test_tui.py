from datetime import datetime, timezone
import asyncio

import pytest

from agent_dashboard.models import AgentState, Snapshot, TmuxLocation
from agent_dashboard.tui import DashboardApp


class FakeClient:
    async def snapshot(self):
        return Snapshot(agents=[AgentState(agent_id="agent-1", session_id="session-1", status="working",
            last_event_type="started", last_event_at=datetime.now(timezone.utc), host_id="host-1",
            working_dir="/tmp", location=TmuxLocation(pane="%1"))])

    async def updates(self):
        updated = AgentState(agent_id="agent-1", session_id="session-1", status="waiting_for_input",
            last_event_type="waiting_for_input", last_event_at=datetime.now(timezone.utc), host_id="host-1",
            working_dir="/tmp", location=TmuxLocation(pane="%1"))
        yield {"agent": updated.model_dump(mode="json")}
        await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_tui_renders_agent_snapshot_e2e():
    app = DashboardApp(client=FakeClient())
    assert app.theme == "nord"
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one("#agents")
        assert str(table.get_cell_at((0, 0))) == "agent-1"
        assert str(table.get_cell_at((0, 1))) in {"working", "waiting_for_input"}


@pytest.mark.asyncio
async def test_tui_refreshes_from_live_event_stream():
    app = DashboardApp(client=FakeClient())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        assert str(app.query_one("#agents").get_cell_at((0, 1))) == "waiting_for_input"
