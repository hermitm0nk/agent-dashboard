import json

import pytest

from agent_dashboard.helper import DbusNotifier, WorkstationHelper


@pytest.mark.asyncio
async def test_helper_allows_only_notification_command():
    calls = []

    async def runner(*args):
        calls.append(args)

    helper = WorkstationHelper(DbusNotifier(runner))
    result = await helper.handle(json.dumps({"type": "notify", "title": "Agent", "body": "Ready"}))
    assert result == {"type": "result", "ok": True}
    assert calls == [("notify-send", "--app-name", "Agent Dashboard", "--", "Agent", "Ready")]


@pytest.mark.asyncio
async def test_helper_rejects_unknown_fields():
    helper = WorkstationHelper(DbusNotifier(lambda *_: None))
    with pytest.raises(ValueError):
        await helper.handle('{"type":"exec","command":"rm -rf /"}')


def test_helper_runner_only_opens_outbound_connection(monkeypatch):
    calls = []

    async def connect_forever(_helper, server_url, host_id):
        calls.append((server_url, host_id))

    monkeypatch.setattr(WorkstationHelper, "connect_forever", connect_forever)

    from agent_dashboard.helper import run_helper
    run_helper(server_url="http://central.test:8000", host_id="workstation-a")

    assert calls == [("http://central.test:8000", "workstation-a")]
