import re

from .models import AgentEvent, AgentState, NotificationRule


def matches(rule: NotificationRule, event: AgentEvent, state: AgentState) -> bool:
    if not rule.enabled:
        return False
    # Working is high-volume state noise. It remains available to users who
    # explicitly create a rule for it, but is not part of an unqualified route.
    if event.event_type == "working" and rule.match.status is None:
        return False
    if (event.event_type == "message" and event.message_role == "user"
            and rule.match.type is None and rule.match.text is None):
        return False
    try:
        public_status = "ready" if state.status.value == "waiting_for_input" else state.status.value
        values = {
            "type": event.event_type,
            "text": event.message or "",
            "agent_id": event.agent_id,
            "agent_type": event.harness,
            "host_id": event.host_id,
            "session_id": event.session_id,
            "status": public_status,
            "working_dir": event.working_dir,
            "model": event.model or state.model or "",
            "chat_title": event.chat_title or state.chat_title or "",
        }
        for field, pattern in rule.match:
            if pattern is None:
                continue
            if field == "status":
                # Accept the old spelling for persisted rules while exposing
                # `ready` as the canonical notification vocabulary.
                if any(re.search(pattern, candidate) is not None
                       for candidate in (public_status, state.status.value)):
                    continue
                return False
            if re.search(pattern, values[field]) is None:
                return False
        return True
    except re.error:
        return False


def evaluate(rules: list[NotificationRule], event: AgentEvent, state: AgentState) -> list[NotificationRule]:
    return [rule for rule in rules if matches(rule, event, state)]
