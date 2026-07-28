import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import (AgentEvent, AgentState, AgentStatus, FirefoxLocation,
                     NotificationRule, TmuxLocation)


def _json_location(location) -> str:
    return json.dumps(location.model_dump(mode="json"), separators=(",", ":"))


def _parse_location(value: str):
    data = json.loads(value)
    # Older rows included the pane's then-current session/window. They are
    # intentionally discarded because only pane_id survives tmux moves.
    return (TmuxLocation.model_validate({"kind": "tmux", "pane": data["pane"]})
            if data["kind"] == "tmux" else FirefoxLocation.model_validate(data))


class Database:
    def __init__(self, path: str | Path = ":memory:"):
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA busy_timeout=5000")
        self.migrate()

    def migrate(self):
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                host_id TEXT NOT NULL,
                working_dir TEXT NOT NULL,
                harness TEXT NOT NULL DEFAULT 'unknown',
                location TEXT NOT NULL,
                model TEXT,
                effort TEXT,
                chat_title TEXT,
                message_role TEXT,
                message TEXT
            );
            CREATE INDEX IF NOT EXISTS events_agent_time ON events(agent_id, timestamp DESC);
            CREATE TABLE IF NOT EXISTS agents (
                agent_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                status TEXT NOT NULL,
                last_event_type TEXT NOT NULL,
                last_event_at TEXT NOT NULL,
                host_id TEXT NOT NULL,
                working_dir TEXT NOT NULL,
                harness TEXT NOT NULL DEFAULT 'unknown',
                location TEXT NOT NULL,
                model TEXT,
                effort TEXT,
                chat_title TEXT,
                last_message TEXT
            );
            CREATE TABLE IF NOT EXISTS notification_rules (
                rule_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                action TEXT NOT NULL CHECK (action IN ('notify', 'silence')),
                enabled INTEGER NOT NULL DEFAULT 1,
                agent_id TEXT,
                harness TEXT,
                host_id TEXT,
                status TEXT,
                status_regex TEXT,
                event_type TEXT
            );
        """)
        for table in ("events", "agents"):
            columns = {row["name"] for row in self.connection.execute(f"PRAGMA table_info({table})")}
            if "harness" not in columns:
                self.connection.execute(f"ALTER TABLE {table} ADD COLUMN harness TEXT NOT NULL DEFAULT 'unknown'")
        event_columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(events)")}
        if "message_role" not in event_columns:
            self.connection.execute("ALTER TABLE events ADD COLUMN message_role TEXT")
        for table in ("events", "agents"):
            columns = {row["name"] for row in self.connection.execute(f"PRAGMA table_info({table})")}
            if "effort" not in columns:
                self.connection.execute(f"ALTER TABLE {table} ADD COLUMN effort TEXT")
        rule_columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(notification_rules)")}
        if "status_regex" not in rule_columns:
            self.connection.execute("ALTER TABLE notification_rules ADD COLUMN status_regex TEXT")
        if "matchers" not in rule_columns:
            self.connection.execute("ALTER TABLE notification_rules ADD COLUMN matchers TEXT")
        if "actions" not in rule_columns:
            self.connection.execute("ALTER TABLE notification_rules ADD COLUMN actions TEXT")
        self.connection.execute("INSERT OR IGNORE INTO schema_migrations VALUES (1, ?)",
                               (datetime.now(timezone.utc).isoformat(),))
        self.connection.commit()

    def record_event(self, event: AgentEvent) -> AgentState:
        state, _ = self.record_event_if_new(event)
        return state

    def record_event_if_new(self, event: AgentEvent) -> tuple[AgentState, bool]:
        """Persist an event and update current state exactly once.

        Hooks deliberately retry delivery, so event IDs are idempotency keys.  An
        older event remains useful history but must not replace newer state.
        """
        status = {
            "started": AgentStatus.STARTED, "working": AgentStatus.WORKING,
            "waiting_for_input": AgentStatus.WAITING_FOR_INPUT,
            "finished": AgentStatus.FINISHED, "error": AgentStatus.ERROR,
            "message": AgentStatus.WORKING,
        }[event.event_type]
        with self.connection:
            existing = self.connection.execute(
                "SELECT * FROM agents WHERE agent_id = ?", (event.agent_id,)
            ).fetchone()
            state = AgentState(
                agent_id=event.agent_id, session_id=event.session_id,
                status=(AgentStatus(existing["status"]) if event.event_type == "message" and existing else status),
                last_event_type=event.event_type, last_event_at=event.timestamp,
                host_id=event.host_id, working_dir=event.working_dir, harness=event.harness,
                location=event.location,
                model=event.model if event.model is not None else (existing["model"] if existing else None),
                effort=event.effort if event.effort is not None else (existing["effort"] if existing else None),
                chat_title=(event.chat_title if event.chat_title is not None
                            else (existing["chat_title"] if existing else None)),
                last_message=(event.message if event.message is not None
                              else (existing["last_message"] if existing else None)),
            )
            inserted = self.connection.execute("""INSERT OR IGNORE INTO events
                (event_id, agent_id, session_id, event_type, timestamp, host_id, working_dir,
                 harness, location, model, effort, chat_title, message_role, message) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (str(event.event_id), event.agent_id, event.session_id, event.event_type,
                 event.timestamp.isoformat(), event.host_id, event.working_dir, event.harness,
                 _json_location(event.location), event.model, event.effort, event.chat_title, event.message_role,
                 event.message)).rowcount
            if not inserted:
                return self._state_for_agent(event.agent_id), False
            self.connection.execute("""INSERT INTO agents
            (agent_id, session_id, status, last_event_type, last_event_at, host_id,
             working_dir, harness, location, model, effort, chat_title, last_message)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(agent_id) DO UPDATE SET session_id=excluded.session_id,
            status=excluded.status, last_event_type=excluded.last_event_type,
            last_event_at=excluded.last_event_at, host_id=excluded.host_id,
            working_dir=excluded.working_dir, location=excluded.location,
             model=excluded.model, effort=excluded.effort, chat_title=excluded.chat_title, last_message=excluded.last_message,
            harness=excluded.harness
            WHERE excluded.last_event_at >= agents.last_event_at""",
            (state.agent_id, state.session_id, state.status.value, state.last_event_type,
             state.last_event_at.isoformat(), state.host_id, state.working_dir, state.harness,
             _json_location(state.location), state.model, state.effort, state.chat_title, state.last_message))
            return self._state_for_agent(event.agent_id), True

    def _state_for_agent(self, agent_id: str) -> AgentState:
        row = self.connection.execute("SELECT * FROM agents WHERE agent_id = ?", (agent_id,)).fetchone()
        if row is None:
            raise LookupError(f"agent {agent_id!r} not found")
        return self._row_to_state(row)

    @staticmethod
    def _row_to_state(row: sqlite3.Row) -> AgentState:
        return AgentState(agent_id=row["agent_id"], session_id=row["session_id"], status=row["status"],
            last_event_type=row["last_event_type"], last_event_at=row["last_event_at"], host_id=row["host_id"],
            working_dir=row["working_dir"], harness=row["harness"], location=_parse_location(row["location"]),
            model=row["model"], effort=row["effort"], chat_title=row["chat_title"], last_message=row["last_message"])

    def snapshot(self) -> list[AgentState]:
        rows = self.connection.execute("SELECT * FROM agents ORDER BY agent_id").fetchall()
        return [self._row_to_state(row) for row in rows]

    def agent(self, agent_id: str) -> AgentState | None:
        row = self.connection.execute("SELECT * FROM agents WHERE agent_id = ?", (agent_id,)).fetchone()
        return self._row_to_state(row) if row else None

    def events_for_agent(self, agent_id: str, *, limit: int = 500) -> list[AgentEvent]:
        """Return an agent's persisted events in conversation order."""
        rows = self.connection.execute(
            "SELECT * FROM (SELECT * FROM events WHERE agent_id = ? "
            "ORDER BY timestamp DESC, event_id DESC LIMIT ?) "
            "ORDER BY timestamp ASC, event_id ASC",
            (agent_id, limit),
        ).fetchall()
        return [AgentEvent(
            event_id=row["event_id"], agent_id=row["agent_id"], session_id=row["session_id"],
            event_type=row["event_type"], timestamp=row["timestamp"], host_id=row["host_id"],
            working_dir=row["working_dir"], harness=row["harness"],
            location=_parse_location(row["location"]), model=row["model"], effort=row["effort"],
            chat_title=row["chat_title"], message_role=row["message_role"], message=row["message"],
        ) for row in rows]

    def rules(self) -> list[NotificationRule]:
        rows = self.connection.execute("SELECT * FROM notification_rules ORDER BY name").fetchall()
        return [NotificationRule(rule_id=row["rule_id"], name=row["name"], enabled=bool(row["enabled"]),
                                 match=json.loads(row["matchers"] or "{}"),
                                 actions=json.loads(row["actions"] or "[]")) for row in rows]

    def save_rule(self, rule: NotificationRule) -> NotificationRule:
        self.connection.execute("""INSERT INTO notification_rules
            (rule_id, name, action, enabled, matchers, actions)
            VALUES (?, ?, 'notify', ?, ?, ?)
            ON CONFLICT(rule_id) DO UPDATE SET name=excluded.name, action=excluded.action,
            enabled=excluded.enabled, matchers=excluded.matchers, actions=excluded.actions""",
            (str(rule.rule_id), rule.name, int(rule.enabled),
             json.dumps(rule.match.model_dump(mode="json"), separators=(",", ":")),
             json.dumps([action.model_dump(mode="json") for action in rule.actions], separators=(",", ":"))))
        self.connection.commit()
        return rule

    def delete_rule(self, rule_id: str) -> bool:
        result = self.connection.execute("DELETE FROM notification_rules WHERE rule_id = ?", (rule_id,))
        self.connection.commit()
        return result.rowcount > 0
