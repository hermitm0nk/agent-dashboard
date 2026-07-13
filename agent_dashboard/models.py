from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class AgentStatus(StrEnum):
    WORKING = "working"
    WAITING_FOR_INPUT = "waiting_for_input"
    FINISHED = "finished"
    ERROR = "error"
    STALE = "stale"


class TmuxLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["tmux"] = "tmux"
    session: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    window: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    pane: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")


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
    location: Location
    model: str | None = Field(default=None, max_length=200)
    chat_title: str | None = Field(default=None, max_length=500)
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
    location: Location
    model: str | None = None
    chat_title: str | None = None
    last_message: str | None = None


class Snapshot(BaseModel):
    agents: list[AgentState]

