import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import AgentEvent, AgentState, AgentStatus, FirefoxLocation, NotificationRule, TmuxLocation


def _json_location(location) -> str:
    return json.dumps(location.model_dump(mode="json"), separators=(",", ":"))


def _parse_location(value: str):
    data = json.loads(value)
    return TmuxLocation.model_validate(data) if data["kind"] == "tmux" else FirefoxLocation.model_validate(data)


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
                chat_title TEXT,
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
                event_type TEXT
            );
        """)
        for table in ("events", "agents"):
            columns = {row["name"] for row in self.connection.execute(f"PRAGMA table_info({table})")}
            if "harness" not in columns:
                self.connection.execute(f"ALTER TABLE {table} ADD COLUMN harness TEXT NOT NULL DEFAULT 'unknown'")
        self.connection.execute("INSERT OR IGNORE INTO schema_migrations VALUES (1, ?)",
                               (datetime.now(timezone.utc).isoformat(),))
        self.connection.commit()

    def record_event(self, event: AgentEvent) -> AgentState:
        status = {
            "started": AgentStatus.WORKING, "working": AgentStatus.WORKING,
            "waiting_for_input": AgentStatus.WAITING_FOR_INPUT,
            "finished": AgentStatus.FINISHED, "error": AgentStatus.ERROR,
            "message": AgentStatus.WORKING,
        }[event.event_type]
        state = AgentState(agent_id=event.agent_id, session_id=event.session_id, status=status,
            last_event_type=event.event_type, last_event_at=event.timestamp, host_id=event.host_id,
            working_dir=event.working_dir, harness=event.harness, location=event.location, model=event.model,
            chat_title=event.chat_title, last_message=event.message)
        self.connection.execute("""INSERT INTO events
            (event_id, agent_id, session_id, event_type, timestamp, host_id, working_dir,
             harness, location, model, chat_title, message) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (str(event.event_id), event.agent_id, event.session_id, event.event_type,
             event.timestamp.isoformat(), event.host_id, event.working_dir, event.harness,
             _json_location(event.location), event.model, event.chat_title, event.message))
        self.connection.execute("""INSERT INTO agents
            (agent_id, session_id, status, last_event_type, last_event_at, host_id,
             working_dir, harness, location, model, chat_title, last_message)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(agent_id) DO UPDATE SET session_id=excluded.session_id,
            status=excluded.status, last_event_type=excluded.last_event_type,
            last_event_at=excluded.last_event_at, host_id=excluded.host_id,
            working_dir=excluded.working_dir, location=excluded.location,
            model=excluded.model, chat_title=excluded.chat_title, last_message=excluded.last_message,
            harness=excluded.harness""",
            (state.agent_id, state.session_id, state.status.value, state.last_event_type,
             state.last_event_at.isoformat(), state.host_id, state.working_dir, state.harness,
             _json_location(state.location), state.model, state.chat_title, state.last_message))
        self.connection.commit()
        return state

    def snapshot(self) -> list[AgentState]:
        rows = self.connection.execute("SELECT * FROM agents ORDER BY agent_id").fetchall()
        return [AgentState(agent_id=row["agent_id"], session_id=row["session_id"], status=row["status"],
            last_event_type=row["last_event_type"], last_event_at=row["last_event_at"], host_id=row["host_id"],
            working_dir=row["working_dir"], harness=row["harness"], location=_parse_location(row["location"]), model=row["model"],
            chat_title=row["chat_title"], last_message=row["last_message"]) for row in rows]

    def rules(self) -> list[NotificationRule]:
        rows = self.connection.execute("SELECT * FROM notification_rules ORDER BY name").fetchall()
        return [NotificationRule(rule_id=row["rule_id"], name=row["name"], action=row["action"],
            enabled=bool(row["enabled"]), agent_id=row["agent_id"], harness=row["harness"],
            host_id=row["host_id"], status=row["status"], event_type=row["event_type"]) for row in rows]

    def save_rule(self, rule: NotificationRule) -> NotificationRule:
        self.connection.execute("""INSERT INTO notification_rules VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(rule_id) DO UPDATE SET name=excluded.name, action=excluded.action,
            enabled=excluded.enabled, agent_id=excluded.agent_id, harness=excluded.harness,
            host_id=excluded.host_id, status=excluded.status, event_type=excluded.event_type""",
            (str(rule.rule_id), rule.name, rule.action, int(rule.enabled), rule.agent_id, rule.harness,
             rule.host_id, rule.status.value if rule.status else None, rule.event_type))
        self.connection.commit()
        return rule

    def delete_rule(self, rule_id: str) -> bool:
        result = self.connection.execute("DELETE FROM notification_rules WHERE rule_id = ?", (rule_id,))
        self.connection.commit()
        return result.rowcount > 0
