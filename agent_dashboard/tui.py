import asyncio
from collections.abc import AsyncIterator

import httpx
from textual.app import App, ComposeResult
from textual.widgets import DataTable, Footer, Header

from .models import AgentState, Snapshot


class DashboardClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    async def snapshot(self) -> Snapshot:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=2) as client:
            response = await client.get("/api/v1/agents")
            response.raise_for_status()
            return Snapshot.model_validate(response.json())

    async def updates(self) -> AsyncIterator[dict]:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=None) as client:
            async with client.stream("GET", "/api/v1/events/stream") as response:
                response.raise_for_status()
                event = None
                async for line in response.aiter_lines():
                    if line.startswith("event: "):
                        event = line[7:]
                    elif line.startswith("data: ") and event == "agent.updated":
                        import json
                        yield json.loads(line[6:])


class DashboardApp(App):
    TITLE = "Agent Dashboard"
    BINDINGS = [("q", "quit", "Quit")]

    def __init__(self, base_url: str = "http://127.0.0.1:8000", client: DashboardClient | None = None):
        super().__init__()
        self.client = client or DashboardClient(base_url)
        self.agents: dict[str, AgentState] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(id="agents")
        yield Footer()

    async def on_mount(self):
        table = self.query_one("#agents", DataTable)
        table.add_columns("Agent", "Status", "Harness/session", "Host", "Last activity")
        await self.load_snapshot()
        self.run_worker(self.watch_updates(), name="dashboard-events")

    async def load_snapshot(self):
        try:
            snapshot = await self.client.snapshot()
        except (httpx.HTTPError, OSError):
            return
        self.agents = {agent.agent_id: agent for agent in snapshot.agents}
        self.refresh_agents()

    async def watch_updates(self):
        while True:
            try:
                async for payload in self.client.updates():
                    agent = AgentState.model_validate(payload["agent"])
                    self.agents[agent.agent_id] = agent
                    self.refresh_agents()
            except asyncio.CancelledError:
                raise
            except (httpx.HTTPError, OSError):
                await asyncio.sleep(1)

    def refresh_agents(self):
        table = self.query_one("#agents", DataTable)
        table.clear()
        for agent in self.agents.values():
            table.add_row(agent.agent_id, agent.status.value, agent.session_id, agent.host_id,
                          agent.last_event_at.isoformat())
