from pathlib import Path

import yaml


EXPECTED_LOCAL_WORKER_QUEUES = {
    "worker-pipeline": "documents.pipeline",
    "worker-ocr": "documents.ocr",
    "worker-metadata": "documents.metadata",
    "worker-chunking": "documents.chunking",
    "worker-external-call": "documents.external_call",
    "worker-recovery": "documents.recovery",
}


def test_local_compose_runs_one_celery_worker_per_queue() -> None:
    compose = yaml.safe_load(Path("docker-compose.yml").read_text())
    services = compose["services"]

    assert "worker" not in services
    for service_name, queue_name in EXPECTED_LOCAL_WORKER_QUEUES.items():
        service = services[service_name]
        command = service["command"]

        assert f"-Q {queue_name}" in command
        assert "documents.pipeline,documents.ocr" not in command
        assert f"-n {service_name}@%h" in command
        assert service["hostname"] == service_name
