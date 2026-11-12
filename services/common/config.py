"""Environment-based configuration for C03 synthetic microservices."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ServiceConfig:
    service_id: str
    service_name: str
    component: str
    environment: str = "lab"
    application: str = "sre-simulation-poc"
    instance_id: str = "instance-lab-01"
    build_version: str = "0.1.0-sim"
    owner_ref: str = "project-initiator-michael"
    dependency_refs: list[str] = field(default_factory=list)
    auth_service_url: str = "http://auth-service:8000"
    transaction_service_url: str = "http://transaction-service:8000"
    ledger_service_url: str = "http://ledger-service:8000"
    notification_service_url: str = "http://notification-service:8000"
    database_url: str = "postgresql://sre_sim:sre_sim_pass@postgres:5432/sre_sim_ledger"
    rabbitmq_url: str = "amqp://sre_sim:sre_sim_pass@rabbitmq:5672/%2F"
    rabbitmq_queue: str = "notifications.transaction.completed"
    rabbitmq_dlq: str = "notifications.transaction.dlq"
    rabbitmq_enabled: bool = True
    request_timeout_sec: float = 4.0
    harness_control_token: str = "SYNTH-HARNESS-CTRL-KEY-C04"
    otel_collector_url: str = "http://otel-collector:4318"
    otel_export_enabled: bool = False


def load_service_config(
    default_service_id: str,
    default_component: str,
    default_dependencies: list[str] | None = None,
) -> ServiceConfig:
    service_id = os.getenv("SERVICE_ID", default_service_id)
    service_name = os.getenv("SERVICE_NAME", service_id)
    deps_raw = os.getenv("DEPENDENCY_REFS", "")
    if deps_raw.strip():
        deps = [d.strip() for d in deps_raw.split(",") if d.strip()]
    else:
        deps = list(default_dependencies or [])

    return ServiceConfig(
        service_id=service_id,
        service_name=service_name,
        component=os.getenv("SERVICE_COMPONENT", default_component),
        environment=os.getenv("SIM_ENVIRONMENT", "lab"),
        application=os.getenv("SIM_APPLICATION", "sre-simulation-poc"),
        instance_id=os.getenv("INSTANCE_ID", f"{service_id}-lab-01"),
        build_version=os.getenv("BUILD_VERSION", "0.1.0-sim"),
        owner_ref=os.getenv("OWNER_REF", "project-initiator-michael"),
        dependency_refs=deps,
        auth_service_url=os.getenv("AUTH_SERVICE_URL", "http://auth-service:8000"),
        transaction_service_url=os.getenv(
            "TRANSACTION_SERVICE_URL", "http://transaction-service:8000"
        ),
        ledger_service_url=os.getenv("LEDGER_SERVICE_URL", "http://ledger-service:8000"),
        notification_service_url=os.getenv(
            "NOTIFICATION_SERVICE_URL", "http://notification-service:8000"
        ),
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql://sre_sim:sre_sim_pass@postgres:5432/sre_sim_ledger",
        ),
        rabbitmq_url=os.getenv(
            "RABBITMQ_URL",
            "amqp://sre_sim:sre_sim_pass@rabbitmq:5672/%2F",
        ),
        rabbitmq_queue=os.getenv(
            "RABBITMQ_QUEUE", "notifications.transaction.completed"
        ),
        rabbitmq_dlq=os.getenv("RABBITMQ_DLQ", "notifications.transaction.dlq"),
        rabbitmq_enabled=os.getenv("RABBITMQ_ENABLED", "true").lower()
        in ("1", "true", "yes"),
        request_timeout_sec=float(os.getenv("REQUEST_TIMEOUT_SEC", "4.0")),
        harness_control_token=os.getenv(
            "HARNESS_CONTROL_TOKEN", "SYNTH-HARNESS-CTRL-KEY-C04"
        ),
        otel_collector_url=os.getenv(
            "OTEL_COLLECTOR_URL", "http://otel-collector:4318"
        ),
        otel_export_enabled=os.getenv("OTEL_EXPORT_ENABLED", "false").lower()
        in ("1", "true", "yes"),
    )

