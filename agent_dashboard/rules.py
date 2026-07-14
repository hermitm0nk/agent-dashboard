from .models import AgentEvent, AgentState, NotificationRule


def matches(rule: NotificationRule, event: AgentEvent, state: AgentState) -> bool:
    if not rule.enabled:
        return False
    return all((expected is None or actual == expected) for expected, actual in (
        (rule.agent_id, event.agent_id), (rule.harness, event.harness),
        (rule.host_id, event.host_id), (rule.status.value if rule.status else None, state.status.value),
        (rule.event_type, event.event_type)))


def evaluate(rules: list[NotificationRule], event: AgentEvent, state: AgentState) -> list[NotificationRule]:
    return [rule for rule in rules if matches(rule, event, state)]
