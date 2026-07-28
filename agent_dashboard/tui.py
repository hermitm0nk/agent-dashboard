import asyncio
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path

import httpx
from rich.markdown import Markdown
from rich.markup import escape
from rich.panel import Panel
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, RichLog, Static

from .models import AgentEvent, AgentState, Snapshot


class DashboardDisconnected(RuntimeError):
    """The server requested that this dashboard client disconnect."""


class DashboardClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    async def snapshot(self) -> Snapshot:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=2) as client:
            response = await client.get("/api/v1/agents")
            response.raise_for_status()
            return Snapshot.model_validate(response.json())

    async def events(self, agent_id: str) -> list[AgentEvent]:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=2) as client:
            response = await client.get(f"/api/v1/agents/{agent_id}/events")
            response.raise_for_status()
            return [AgentEvent.model_validate(item) for item in response.json()]

    async def search_messages(self, query: str) -> list[str]:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=2) as client:
            response = await client.get("/api/v1/search/agents", params={"q": query})
            response.raise_for_status()
            return [str(agent_id) for agent_id in response.json()]

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
                    elif line.startswith("data: ") and event == "disconnect":
                        raise DashboardDisconnected("server requested disconnect")

    async def focus(self, agent_id: str) -> None:
        await self._post(f"/api/v1/agents/{agent_id}/focus", {})

    async def set_seen(self, agent_id: str, seen: bool) -> AgentState:
        return AgentState.model_validate(
            await self._post(f"/api/v1/agents/{agent_id}/seen", {"seen": seen})
        )

    async def set_archived(self, agent_id: str, archived: bool) -> AgentState:
        return AgentState.model_validate(
            await self._post(f"/api/v1/agents/{agent_id}/archive", {"archived": archived})
        )

    async def mark_all_seen(self) -> Snapshot:
        return Snapshot.model_validate(await self._post("/api/v1/agents/seen-all", None))

    async def _post(self, path: str, body: dict | None) -> dict:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=2) as client:
            response = await client.post(path, json=body)
            response.raise_for_status()
            return response.json()


def _working_directory(path: str) -> str:
    try:
        return str(Path(path).expanduser()).replace(str(Path.home()), "~", 1)
    except (OSError, ValueError):
        return path


def _relative_time(value: datetime) -> str:
    seconds = max(0, (datetime.now(value.tzinfo) - value).total_seconds())
    if seconds < 60:
        return "now"
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h"
    return f"{int(seconds // 86400)}d"


def _status_badge(agent: AgentState) -> Text:
    badges = {
        "working": ("*", "bold #ebcb8b"),
        "started": ("*", "bold #ebcb8b"),
        "waiting_for_input": (">", "bold #a3be8c"),
        "finished": ("-", "#8fbcbb"),
        "error": ("x", "bold #bf616a"),
        "stale": ("~", "#aeb8c8"),
    }
    label, style = badges[agent.status.value]
    return Text(label, style=style)


class ConversationScreen(Screen):
    BINDINGS = [
        Binding("escape,backspace,h", "back", "Back"),
        Binding("j", "scroll_down", "Down", show=False),
        Binding("k", "scroll_up", "Up", show=False),
        Binding("ctrl+d", "page_down", "Page down", show=False),
        Binding("ctrl+u", "page_up", "Page up", show=False),
        Binding("g", "scroll_home", "Top", show=False),
        Binding("G", "scroll_end", "Bottom", show=False),
        Binding("F", "focus_agent", "Focus"),
        Binding("S", "toggle_seen", "Seen"),
        Binding("A", "toggle_archive", "Archive"),
        Binding("R", "reload", "Reload"),
    ]

    def __init__(self, agent_id: str):
        super().__init__()
        self.agent_id = agent_id

    @property
    def dashboard(self) -> "DashboardApp":
        return self.app  # type: ignore[return-value]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(id="conversation-summary")
        yield RichLog(id="messages", wrap=True, markup=False, auto_scroll=True)
        yield Footer()

    async def on_mount(self) -> None:
        self.refresh_summary()
        await self.load_messages()
        self.query_one("#messages", RichLog).focus()

    def refresh_summary(self) -> None:
        agent = self.dashboard.agents.get(self.agent_id)
        if agent is None:
            return
        model = agent.model or agent.harness
        effort = f" · {agent.effort}" if agent.effort else ""
        summary = Text()
        summary.append_text(_status_badge(agent))
        summary.append(f"  {_working_directory(agent.working_dir)}", style="bold")
        summary.append(f"  {model}{effort} · {agent.host_id}", style="#aeb8c8")
        if agent.unseen:
            summary.append("  !", style="bold #88c0d0")
        if agent.archived:
            summary.append("  [archived]", style="#ebcb8b")
        self.query_one("#conversation-summary", Static).update(summary)

    async def load_messages(self) -> None:
        log = self.query_one("#messages", RichLog)
        log.clear()
        try:
            events = await self.dashboard.client.events(self.agent_id)
        except (httpx.HTTPError, OSError) as exc:
            log.write(Text(f"Could not load messages: {exc}", style="bold red"))
            return
        visible = [event for event in events if event.event_type in ("message", "error")]
        if not visible:
            log.write(Text("No messages recorded for this session.", style="#aeb8c8"))
            return
        for event in visible:
            self.write_event(event)

    def write_event(self, event: AgentEvent) -> None:
        role = "You" if event.message_role == "user" else "Agent"
        color = "#81a1c1" if event.message_role == "user" else "#88c0d0"
        if event.event_type == "error":
            role, color = "Error", "#bf616a"
        timestamp = event.timestamp.astimezone().strftime("%H:%M")
        subtitle = f"{event.model or ''}{f' · {event.effort}' if event.effort else ''}".strip()
        content = Markdown(event.message or "Agent reported an error")
        self.query_one("#messages", RichLog).write(Panel(
            content,
            title=f"[bold {color}]{role}[/] [#aeb8c8]{timestamp}[/]",
            subtitle=f"[#aeb8c8]{subtitle}[/]" if subtitle else None,
            border_style=color,
            padding=(0, 1),
        ))

    def action_back(self) -> None:
        self.app.pop_screen()

    async def action_focus_agent(self) -> None:
        await self.dashboard.focus_agent(self.agent_id)

    async def action_toggle_seen(self) -> None:
        await self.dashboard.toggle_seen(self.agent_id)

    async def action_toggle_archive(self) -> None:
        if await self.dashboard.toggle_archive(self.agent_id):
            self.app.pop_screen()

    async def action_reload(self) -> None:
        await self.load_messages()

    def action_scroll_down(self) -> None:
        self.query_one("#messages", RichLog).scroll_relative(y=3)

    def action_scroll_up(self) -> None:
        self.query_one("#messages", RichLog).scroll_relative(y=-3)

    def action_page_down(self) -> None:
        log = self.query_one("#messages", RichLog)
        log.scroll_relative(y=max(1, log.size.height // 2))

    def action_page_up(self) -> None:
        log = self.query_one("#messages", RichLog)
        log.scroll_relative(y=-max(1, log.size.height // 2))

    def action_scroll_home(self) -> None:
        self.query_one("#messages", RichLog).scroll_home()

    def action_scroll_end(self) -> None:
        self.query_one("#messages", RichLog).scroll_end()


class DashboardApp(App):
    TITLE = "Agent Dashboard"
    CSS = """
    Screen { background: #242933; color: #e5e9f0; }
    Header, Footer { background: #2e3440; color: #e5e9f0; }
    #agents { height: 1fr; background: #242933; border: solid #3b4252; }
    #agents > .datatable--header { background: #2b313c; color: #88c0d0; text-style: bold; }
    #agents > .datatable--even-row { background: #242933; }
    #agents > .datatable--odd-row { background: #272d38; }
    #agents > .datatable--hover { background: #343c49; }
    #agents > .datatable--cursor { background: #4f6f98; color: #eceff4; text-style: bold; }
    #search { height: 3; margin: 0 1; padding: 0 1; background: #242933;
              border: tall #5e81ac; color: #eceff4; }
    #list-summary, #conversation-summary {
        height: auto; min-height: 3; padding: 1 2;
        background: #2b313c; border-bottom: solid #3b4252;
    }
    #messages { height: 1fr; padding: 1 2; background: #2e3440; scrollbar-color: #5e81ac; }
    """
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("ctrl+d", "page_down", "Page down", show=False),
        Binding("ctrl+u", "page_up", "Page up", show=False),
        Binding("g", "first", "First", show=False),
        Binding("G", "last", "Last", show=False),
        Binding("enter,l", "open_session", "Open"),
        Binding("/", "search", "Search"),
        Binding("escape", "clear_search", "Clear search", show=False),
        Binding("F", "focus_selected", "Focus"),
        Binding("S", "toggle_seen_selected", "Seen"),
        Binding("A", "toggle_archive_selected", "Archive"),
        Binding("X", "toggle_archive_view", "Active/Archive"),
        Binding("M", "mark_all_seen", "All seen"),
        Binding("R", "reload", "Reload"),
    ]

    def __init__(self, base_url: str = "http://127.0.0.1:8000", client: DashboardClient | None = None):
        super().__init__()
        self.theme = "nord"
        self.client = client or DashboardClient(base_url)
        self.agents: dict[str, AgentState] = {}
        self.ordered_agent_ids: list[str] = []
        self.show_archive = False
        self.filter_query = ""
        self.message_match_ids: list[str] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(id="list-summary")
        yield Input(placeholder="Filter sessions…", id="search")
        yield DataTable(id="agents")
        yield Footer()

    async def on_mount(self):
        table = self.query_one("#agents", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        table.add_columns("", "Dir", "Model", "Type", "Host", "Age")
        self.query_one("#search", Input).display = False
        await self.load_snapshot()
        table.focus()
        self.run_worker(self.watch_updates(), name="dashboard-events")

    async def load_snapshot(self):
        try:
            snapshot = await self.client.snapshot()
        except (httpx.HTTPError, OSError):
            self.notify("Dashboard server unavailable", severity="error")
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
                    if isinstance(self.screen, ConversationScreen) and self.screen.agent_id == agent.agent_id:
                        self.screen.refresh_summary()
                        if payload.get("event"):
                            event = AgentEvent.model_validate(payload["event"])
                            if event.event_type in ("message", "error"):
                                self.screen.write_event(event)
            except asyncio.CancelledError:
                raise
            except DashboardDisconnected:
                self.exit()
                return
            except (httpx.HTTPError, OSError):
                await asyncio.sleep(1)

    def refresh_agents(self):
        try:
            table = self.query_one("#agents", DataTable)
        except NoMatches:
            # SSE updates may race with Textual unmounting the root screen
            # during shutdown. Preserve state, but there is nothing to draw.
            return
        selected = None
        if self.ordered_agent_ids:
            selected = self.ordered_agent_ids[
                min(max(table.cursor_row, 0), len(self.ordered_agent_ids) - 1)
            ]
        visible = [agent for agent in self.agents.values() if agent.archived == self.show_archive]
        query = self.filter_query.casefold()
        if query:
            message_matches = set(self.message_match_ids)
            visible = [
                agent for agent in visible
                if query in " ".join((
                    agent.agent_id, agent.session_id, agent.status.value,
                    agent.working_dir, agent.harness, agent.host_id,
                    agent.model or "", agent.effort or "", agent.chat_title or "",
                )).casefold() or agent.agent_id in message_matches
            ]
        if query:
            message_rank = {agent_id: rank for rank, agent_id in enumerate(self.message_match_ids)}
            visible.sort(key=lambda agent: (
                query not in " ".join((
                    agent.agent_id, agent.session_id, agent.status.value,
                    agent.working_dir, agent.harness, agent.host_id,
                    agent.model or "", agent.effort or "", agent.chat_title or "",
                )).casefold(),
                message_rank.get(agent.agent_id, len(message_rank)),
                not agent.unseen,
                agent.status.value != "waiting_for_input",
            ))
        else:
            visible.sort(key=lambda agent: (
                not agent.unseen,
                agent.status.value != "waiting_for_input",
                -agent.last_event_at.timestamp(),
            ))
        self.ordered_agent_ids = [agent.agent_id for agent in visible]
        table.clear()
        for agent in visible:
            indicators = Text()
            indicators.append("!" if agent.unseen else " ", style="bold #88c0d0")
            indicators.append(" ")
            indicators.append_text(_status_badge(agent))
            model = agent.model or "model unavailable"
            if agent.effort:
                model += f" · {agent.effort}"
            table.add_row(
                indicators, _working_directory(agent.working_dir), model,
                agent.harness, agent.host_id, _relative_time(agent.last_event_at),
                key=agent.agent_id,
            )
        unseen = sum(agent.unseen for agent in visible)
        view = "ARCHIVE" if self.show_archive else "ACTIVE"
        self.query_one("#list-summary", Static).update(
            f"[bold #88c0d0]{view}[/]  {len(visible)} sessions  "
            f"[bold #88c0d0]{unseen} unseen[/]  "
            f"{f'[#aeb8c8]filter: {escape(self.filter_query)}[/]  ' if self.filter_query else ''}"
            "[#aeb8c8]* busy · > ready · ! unseen · / search[/]"
        )
        if selected in self.ordered_agent_ids:
            table.move_cursor(row=self.ordered_agent_ids.index(selected))

    @property
    def selected_agent_id(self) -> str | None:
        if not self.ordered_agent_ids:
            return None
        try:
            row = self.query_one("#agents", DataTable).cursor_row
        except NoMatches:
            return None
        return self.ordered_agent_ids[min(max(row, 0), len(self.ordered_agent_ids) - 1)]

    def action_open_session(self) -> None:
        if self.selected_agent_id:
            self.push_screen(ConversationScreen(self.selected_agent_id))

    def action_cursor_down(self) -> None:
        table = self.query_one("#agents", DataTable)
        if self.ordered_agent_ids:
            table.move_cursor(row=min(table.cursor_row + 1, len(self.ordered_agent_ids) - 1))

    def action_cursor_up(self) -> None:
        table = self.query_one("#agents", DataTable)
        if self.ordered_agent_ids:
            table.move_cursor(row=max(table.cursor_row - 1, 0))

    def action_page_down(self) -> None:
        table = self.query_one("#agents", DataTable)
        if self.ordered_agent_ids:
            table.move_cursor(row=min(
                table.cursor_row + max(1, table.size.height // 2),
                len(self.ordered_agent_ids) - 1,
            ))

    def action_page_up(self) -> None:
        table = self.query_one("#agents", DataTable)
        if self.ordered_agent_ids:
            table.move_cursor(row=max(table.cursor_row - max(1, table.size.height // 2), 0))

    def action_first(self) -> None:
        if self.ordered_agent_ids:
            self.query_one("#agents", DataTable).move_cursor(row=0)

    def action_last(self) -> None:
        if self.ordered_agent_ids:
            self.query_one("#agents", DataTable).move_cursor(row=len(self.ordered_agent_ids) - 1)

    def action_search(self) -> None:
        search = self.query_one("#search", Input)
        search.display = True
        search.focus()

    def action_clear_search(self) -> None:
        search = self.query_one("#search", Input)
        if search.display:
            search.value = ""
            search.display = False
            self.filter_query = ""
            self.message_match_ids = []
            self.refresh_agents()
            self.query_one("#agents", DataTable).focus()

    async def action_focus_selected(self) -> None:
        if self.selected_agent_id:
            await self.focus_agent(self.selected_agent_id)

    async def focus_agent(self, agent_id: str) -> None:
        try:
            await self.client.focus(agent_id)
            self.notify("Focus requested")
        except (httpx.HTTPError, OSError) as exc:
            self.notify(f"Focus failed: {exc}", severity="error")

    async def action_toggle_seen_selected(self) -> None:
        if self.selected_agent_id:
            await self.toggle_seen(self.selected_agent_id)

    async def toggle_seen(self, agent_id: str) -> None:
        agent = self.agents[agent_id]
        try:
            updated = await self.client.set_seen(agent_id, agent.unseen)
        except (httpx.HTTPError, OSError) as exc:
            self.notify(f"Seen state failed: {exc}", severity="error")
            return
        self.agents[agent_id] = updated
        self.refresh_agents()
        if isinstance(self.screen, ConversationScreen):
            self.screen.refresh_summary()

    async def action_toggle_archive_selected(self) -> None:
        if self.selected_agent_id:
            await self.toggle_archive(self.selected_agent_id)

    async def toggle_archive(self, agent_id: str) -> bool:
        agent = self.agents[agent_id]
        try:
            updated = await self.client.set_archived(agent_id, not agent.archived)
        except (httpx.HTTPError, OSError) as exc:
            self.notify(f"Archive failed: {exc}", severity="error")
            return False
        self.agents[agent_id] = updated
        self.refresh_agents()
        self.notify("Restored" if agent.archived else "Archived")
        return True

    def action_toggle_archive_view(self) -> None:
        self.show_archive = not self.show_archive
        self.refresh_agents()

    async def action_mark_all_seen(self) -> None:
        try:
            snapshot = await self.client.mark_all_seen()
        except (httpx.HTTPError, OSError) as exc:
            self.notify(f"Mark all failed: {exc}", severity="error")
            return
        self.agents = {agent.agent_id: agent for agent in snapshot.agents}
        self.refresh_agents()

    async def action_reload(self) -> None:
        await self.load_snapshot()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search":
            self.filter_query = event.value
            self.message_match_ids = []
            self.refresh_agents()
            if event.value.strip():
                self.run_worker(
                    self.search_message_history(event.value),
                    name="message-search",
                    group="message-search",
                    exclusive=True,
                    exit_on_error=False,
                )

    async def search_message_history(self, query: str) -> None:
        try:
            matches = await self.client.search_messages(query)
        except (httpx.HTTPError, OSError):
            return
        if self.filter_query == query:
            self.message_match_ids = matches
            self.refresh_agents()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search":
            self.query_one("#agents", DataTable).focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.push_screen(ConversationScreen(str(event.row_key.value)))
