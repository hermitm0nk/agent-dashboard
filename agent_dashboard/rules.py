import re

from .models import AgentEvent, AgentState, NotificationRule


def matches(rule: NotificationRule, event: AgentEvent, state: AgentState) -> bool:
    if not rule.enabled:
        return False
    try:
        values = {
            "type": event.event_type,
            "text": event.message or "",
            "agent_id": event.agent_id,
            "agent_type": event.harness,
            "host_id": event.host_id,
            "session_id": event.session_id,
            "status": state.status.value,
            "working_dir": event.working_dir,
            "model": event.model or state.model or "",
            "chat_title": event.chat_title or state.chat_title or "",
        }
        return all(pattern is None or re.search(pattern, values[field]) is not None
                   for field, pattern in rule.match)
    except re.error:
        return False


def evaluate(rules: list[NotificationRule], event: AgentEvent, state: AgentState) -> list[NotificationRule]:
    return [rule for rule in rules if matches(rule, event, state)]
