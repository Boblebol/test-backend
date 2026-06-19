import json
from datetime import datetime, timezone
from uuid import uuid4

from app.domain.enums import DocumentStatus, ProcessingStepName, ProcessingStepStatus
from app.modules.processing.progress import (
    ProgressEvent,
    RedisProgressPublisher,
    RedisProgressSubscriber,
    progress_channel,
)


def test_redis_progress_publisher_sends_expected_channel_and_payload() -> None:
    redis_client = FakeRedis()
    org_id = uuid4()
    document_id = uuid4()

    RedisProgressPublisher(redis_client).publish(
        ProgressEvent(
            org_id=org_id,
            document_id=document_id,
            step=ProcessingStepName.METADATA,
            step_status=ProcessingStepStatus.RETRYING,
            document_status=DocumentStatus.PROCESSING,
            occurred_at=datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc),
        )
    )

    assert len(redis_client.published) == 1
    channel, payload = redis_client.published[0]
    assert channel == f"document-progress:{org_id}:{document_id}"
    assert json.loads(payload) == {
        "org_id": str(org_id),
        "document_id": str(document_id),
        "step": "metadata",
        "step_status": "retrying",
        "document_status": "processing",
        "occurred_at": "2026-06-14T12:00:00+00:00",
    }


def test_progress_channel_is_scoped_by_org_and_document() -> None:
    org_id = uuid4()
    document_id = uuid4()

    assert progress_channel(org_id, document_id) == f"document-progress:{org_id}:{document_id}"


def test_redis_progress_subscriber_reads_messages_from_subscribed_channel() -> None:
    redis_client = FakeRedisForSubscriber([None, {"type": "message", "data": "payload"}])
    subscriber = RedisProgressSubscriber(redis_client)

    assert subscriber.next_message(timeout_seconds=1) is None
    subscriber.subscribe("document-progress:org:doc")

    assert subscriber.next_message(timeout_seconds=15) is None
    assert subscriber.next_message(timeout_seconds=15) == "payload"
    assert redis_client.pubsub_instance.subscribed_channels == ["document-progress:org:doc"]
    assert redis_client.pubsub_instance.timeouts == [15, 15]

    subscriber.close()

    assert redis_client.pubsub_instance.closed is True


class FakeRedis:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    def publish(self, channel: str, payload: str) -> None:
        self.published.append((channel, payload))


class FakeRedisForSubscriber:
    def __init__(self, messages: list[dict | None]) -> None:
        self.pubsub_instance = FakePubSub(messages)

    def pubsub(self):
        return self.pubsub_instance


class FakePubSub:
    def __init__(self, messages: list[dict | None]) -> None:
        self.messages = messages
        self.subscribed_channels: list[str] = []
        self.timeouts: list[int] = []
        self.closed = False

    def subscribe(self, channel: str) -> None:
        self.subscribed_channels.append(channel)

    def get_message(self, *, ignore_subscribe_messages: bool, timeout: int):
        assert ignore_subscribe_messages is True
        self.timeouts.append(timeout)
        return self.messages.pop(0)

    def close(self) -> None:
        self.closed = True
