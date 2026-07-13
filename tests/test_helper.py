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
    assert calls == [("notify-send", "--", "Agent", "Ready")]


@pytest.mark.asyncio
async def test_helper_rejects_unknown_fields():
    helper = WorkstationHelper(DbusNotifier(lambda *_: None))
    with pytest.raises(ValueError):
        await helper.handle('{"type":"exec","command":"rm -rf /"}')
