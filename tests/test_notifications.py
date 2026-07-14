import asyncio
from uuid import uuid4

import httpx
import pytest

from agent_dashboard.models import NotificationMessage
from agent_dashboard.notifications import NtfyAdapter, NotificationQueue, WebPushAdapter


def message():
    return NotificationMessage(delivery_id=uuid4(), title="Agent", body="Needs input", topic="demo")


@pytest.mark.asyncio
async def test_ntfy_posts_title_and_body():
    seen = {}

    def handler(request):
        seen.update({"url": str(request.url), "title": request.headers["Title"], "body": request.content})
        return httpx.Response(200)

    adapter = NtfyAdapter("alerts", server="http://ntfy.test", client=httpx.AsyncClient(
        transport=httpx.MockTransport(handler)))
    await adapter.deliver(message())
    await adapter.client.aclose()
    assert seen == {"url": "http://ntfy.test/alerts", "title": "Agent", "body": b"Needs input"}


@pytest.mark.asyncio
async def test_queue_retries_and_records_final_failure():
    attempts, records = [], []

    class Broken:
        name = "broken"
        async def deliver(self, _message):
            attempts.append(1)
            raise RuntimeError("offline")

    async def record(item):
        records.append(item)

    queue = NotificationQueue([], record=record)
    await queue.enqueue(message(), Broken())
    result = await queue.run_once()
    assert result.status == "failed" and result.attempts == 3
    assert len(attempts) == 3 and records[-1].error == "offline"


@pytest.mark.asyncio
async def test_webpush_adapter_delegates_to_sender():
    delivered = []
    adapter = WebPushAdapter(lambda item: _append(delivered, item))
    await adapter.deliver(message())
    assert len(delivered) == 1


async def _append(target, item):
    target.append(item)
