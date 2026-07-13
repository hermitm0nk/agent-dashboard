import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

import httpx

from .models import DeliveryRecord, NotificationMessage


class DeliveryAdapter(Protocol):
    name: str

    async def deliver(self, message: NotificationMessage) -> None: ...


class NtfyAdapter:
    name = "ntfy"

    def __init__(self, topic: str, server: str = "https://ntfy.sh", client: httpx.AsyncClient | None = None):
        self.topic, self.server, self.client = topic, server.rstrip("/"), client

    async def deliver(self, message: NotificationMessage) -> None:
        owns_client = self.client is None
        client = self.client or httpx.AsyncClient(timeout=2)
        try:
            response = await client.post(f"{self.server}/{self.topic}", content=message.body,
                                         headers={"Title": message.title})
            response.raise_for_status()
        finally:
            if owns_client:
                await client.aclose()


class WebPushAdapter:
    name = "webpush"

    def __init__(self, sender: Callable[[NotificationMessage], Awaitable[None]]):
        self.sender = sender

    async def deliver(self, message: NotificationMessage) -> None:
        await self.sender(message)


@dataclass
class NotificationQueue:
    adapters: list[DeliveryAdapter]
    record: Callable[[DeliveryRecord], Awaitable[None]] | None = None
    maxsize: int = 100

    def __post_init__(self):
        self.queue: asyncio.Queue[tuple[NotificationMessage, DeliveryAdapter]] = asyncio.Queue(self.maxsize)

    async def enqueue(self, message: NotificationMessage, adapter: DeliveryAdapter) -> bool:
        try:
            self.queue.put_nowait((message, adapter))
            await self._record(DeliveryRecord(delivery_id=message.delivery_id, backend=adapter.name, status="queued"))
            return True
        except asyncio.QueueFull:
            return False

    async def run_once(self) -> DeliveryRecord | None:
        if self.queue.empty():
            return None
        message, adapter = await self.queue.get()
        error = None
        for attempt in range(1, 4):
            try:
                await adapter.deliver(message)
                result = DeliveryRecord(delivery_id=message.delivery_id, backend=adapter.name,
                                        status="delivered", attempts=attempt)
                await self._record(result)
                self.queue.task_done()
                return result
            except Exception as exc:  # delivery must not affect agent state
                error = str(exc)
                if attempt < 3:
                    await asyncio.sleep(0.1 * (2 ** (attempt - 1)))
        result = DeliveryRecord(delivery_id=message.delivery_id, backend=adapter.name,
                                status="failed", attempts=3, error=error)
        await self._record(result)
        self.queue.task_done()
        return result

    async def _record(self, record: DeliveryRecord):
        if self.record:
            await self.record(record)
