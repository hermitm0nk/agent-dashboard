from datetime import datetime, timezone
from enum import StrEnum
import re
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class AgentStatus(StrEnum):
    STARTED = "started"
    WORKING = "working"
    WAITING_FOR_INPUT = "waiting_for_input"
    FINISHED = "finished"
    ERROR = "error"
    STALE = "stale"


class TmuxLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["tmux"] = "tmux"
    pane: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:$@%-]+$")


class FirefoxLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["firefox"] = "firefox"
    window_tab: str = Field(pattern=r"^[0-9]+\.[0-9]+$")
    url: HttpUrl
    title: str = Field(default="", max_length=500)


Location = Annotated[TmuxLocation | FirefoxLocation, Field(discriminator="kind")]


class AgentEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: UUID
    agent_id: str = Field(min_length=1, max_length=200)
    session_id: str = Field(min_length=1, max_length=200)
    event_type: Literal["started", "working", "waiting_for_input", "message", "finished", "error"]
    timestamp: datetime
    host_id: str = Field(min_length=1, max_length=200)
    working_dir: str = Field(min_length=1, max_length=4096)
    harness: str = Field(default="unknown", min_length=1, max_length=100)
    location: Location
    model: str | None = Field(default=None, max_length=200)
    chat_title: str | None = Field(default=None, max_length=500)
    message_role: Literal["user", "assistant"] | None = None
    message: str | None = Field(default=None, max_length=10000)

    @model_validator(mode="after")
    def normalize_timestamp(self):
        if self.timestamp.tzinfo is None:
            raise ValueError("timestamp must include a timezone")
        self.timestamp = self.timestamp.astimezone(timezone.utc)
        return self


class AgentState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str
    session_id: str
    status: AgentStatus
    last_event_type: str
    last_event_at: datetime
    host_id: str
    working_dir: str
    harness: str = "unknown"
    location: Location
    model: str | None = None
    chat_title: str | None = None
    last_message: str | None = None


class Snapshot(BaseModel):
    agents: list[AgentState]


class NotificationMatchers(BaseModel):
    """Regular expressions searched within normalized agent-event attributes."""
    model_config = ConfigDict(extra="forbid")
    type: str | None = Field(default=None, max_length=500)
    text: str | None = Field(default=None, max_length=500)
    agent_id: str | None = Field(default=None, max_length=500)
    agent_type: str | None = Field(default=None, max_length=500)
    host_id: str | None = Field(default=None, max_length=500)
    session_id: str | None = Field(default=None, max_length=500)
    status: str | None = Field(default=None, max_length=500)
    working_dir: str | None = Field(default=None, max_length=500)
    model: str | None = Field(default=None, max_length=500)
    chat_title: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_regexes(self):
        for field, value in self:
            if value is not None:
                try:
                    re.compile(value)
                except re.error as exc:
                    raise ValueError(f"invalid {field} regex: {exc}") from exc
        return self


class NativeNotificationAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["native"] = "native"
    hostname_regex: str = Field(default=".*", min_length=1, max_length=500)


class WebPushNotificationAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["webpush"] = "webpush"
    client_ids_regex: str = Field(default=".*", min_length=1, max_length=500)


class NtfyNotificationAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["ntfy"] = "ntfy"
    topic: str = Field(min_length=1, max_length=200)
    server: HttpUrl = Field(default="https://ntfy.sh", validate_default=True)


NotificationAction = Annotated[
    NativeNotificationAction | WebPushNotificationAction | NtfyNotificationAction,
    Field(discriminator="type"),
]


class NotificationRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rule_id: UUID
    name: str = Field(min_length=1, max_length=200)
    enabled: bool = True
    match: NotificationMatchers = Field(default_factory=NotificationMatchers)
    actions: list[NotificationAction] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def validate_action_regexes(self):
        for action in self.actions:
            pattern = (action.hostname_regex if isinstance(action, NativeNotificationAction)
                       else action.client_ids_regex if isinstance(action, WebPushNotificationAction)
                       else None)
            if pattern is not None:
                try:
                    re.compile(pattern)
                except re.error as exc:
                    raise ValueError(f"invalid {action.type} target regex: {exc}") from exc
        return self


class NotificationDecision(BaseModel):
    rule_id: UUID
    rule_name: str
    actions: list[NotificationAction]


NotificationChannel = Literal["native", "webpush", "ntfy"]


class EventAccepted(BaseModel):
    type: str
    agent: AgentState
    notifications: list[NotificationDecision] = Field(default_factory=list)


class FocusRequest(BaseModel):
    """A focus request; routing is determined from the agent's host."""
    model_config = ConfigDict(extra="forbid")


class NotificationMessage(BaseModel):
    delivery_id: UUID
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=10000)
    topic: str | None = Field(default=None, max_length=200)
    url: HttpUrl | None = None
    channel: NotificationChannel | None = None


class DeliveryRecord(BaseModel):
    delivery_id: UUID
    backend: str
    status: Literal["queued", "delivered", "failed"]
    attempts: int = 0
    error: str | None = None
