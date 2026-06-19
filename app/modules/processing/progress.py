import json
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.enums import DocumentStatus, ProcessingStepName, ProcessingStepStatus


@dataclass(frozen=True)
class ProgressEvent:
    org_id: UUID
    document_id: UUID
    step: ProcessingStepName
    step_status: ProcessingStepStatus
    document_status: DocumentStatus
    occurred_at: datetime


class ProgressPublisher(Protocol):
    def publish(self, event: ProgressEvent) -> None:
        pass


class ProgressSubscriber(Protocol):
    def subscribe(self, channel: str) -> None:
        pass

    def next_message(self, timeout_seconds: int) -> str | None:
        pass

    def close(self) -> None:
        pass


class NullProgressPublisher:
    def publish(self, event: ProgressEvent) -> None:
        pass


class CollectingProgressPublisher:
    def __init__(self) -> None:
        self.events: list[ProgressEvent] = []

    def publish(self, event: ProgressEvent) -> None:
        self.events.append(event)


class RedisProgressPublisher:
    def __init__(self, redis_client) -> None:
        self.redis_client = redis_client

    def publish(self, event: ProgressEvent) -> None:
        self.redis_client.publish(
            progress_channel(event.org_id, event.document_id),
            _payload(event),
        )


class RedisProgressSubscriber:
    def __init__(self, redis_client) -> None:
        self.redis_client = redis_client
        self.pubsub = None

    def subscribe(self, channel: str) -> None:
        self.pubsub = self.redis_client.pubsub()
        self.pubsub.subscribe(channel)

    def next_message(self, timeout_seconds: int) -> str | None:
        if self.pubsub is None:
            return None
        message = self.pubsub.get_message(
            ignore_subscribe_messages=True,
            timeout=timeout_seconds,
        )
        if message is None:
            return None
        return message["data"]

    def close(self) -> None:
        if self.pubsub is not None:
            self.pubsub.close()
            self.pubsub = None


def build_redis_progress_publisher(redis_url: str) -> RedisProgressPublisher:
    from redis import Redis

    return RedisProgressPublisher(Redis.from_url(redis_url, decode_responses=True))


def build_redis_progress_subscriber(redis_url: str) -> RedisProgressSubscriber:
    from redis import Redis

    return RedisProgressSubscriber(Redis.from_url(redis_url, decode_responses=True))


def publish_collected_events(
    collected: CollectingProgressPublisher,
    publisher: ProgressPublisher,
) -> None:
    for event in collected.events:
        publisher.publish(event)


def progress_channel(org_id: UUID, document_id: UUID) -> str:
    return f"document-progress:{org_id}:{document_id}"


def _payload(event: ProgressEvent) -> str:
    return json.dumps(
        {
            "org_id": str(event.org_id),
            "document_id": str(event.document_id),
            "step": event.step.value,
            "step_status": event.step_status.value,
            "document_status": event.document_status.value,
            "occurred_at": event.occurred_at.isoformat(),
        },
        separators=(",", ":"),
    )
