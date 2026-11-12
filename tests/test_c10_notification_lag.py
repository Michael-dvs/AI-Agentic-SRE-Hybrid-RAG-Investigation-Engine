"""Consumer backlog signals originate in queue observations, not fabricated events."""

import sys
from contextvars import Context
from types import SimpleNamespace

from observability.alerts import evaluate_alert_rules
from services.common.config import ServiceConfig
from services.common.telemetry import set_telemetry_context
from services.notification_service import app as notification_app


def test_consumer_lag_backlog_logs_and_real_alert_rule(monkeypatch):
    config = ServiceConfig(
        service_id="notification-service",
        service_name="notification-custom",
        component="notification",
        environment="synthetic-lab",
        build_version="test-build",
    )
    processor = notification_app.NotificationProcessor(config)
    worker = notification_app.RabbitMQConsumerWorker(config, processor)
    processor.set_consumer_lag(True, delay_ms=500)
    # Zero backlog, sustained backlog, zero reset, immediate reactivation, recovery.
    observations = [(0, 9.0), (2, 10.0), (3, 10.5), (4, 11.0),
                    (0, 11.05), (5, 11.1), (6, 11.2)]
    state = {"index": 0, "time": 0.0, "gets": 0}
    logs = []
    actual_emit = notification_app.emit_structured_log

    def capture_log(**kwargs):
        log = actual_emit(**kwargs)
        logs.append(log)
        return log

    class Channel:
        def queue_declare(self, queue, durable, passive=False):
            if passive:
                assert queue == config.rabbitmq_queue
                depth, state["time"] = observations[state["index"]]
                return SimpleNamespace(method=SimpleNamespace(message_count=depth))
            return None

        def basic_qos(self, prefetch_count):
            assert prefetch_count == 10

        def basic_get(self, queue, auto_ack):
            assert not processor.consumer_lag_active
            assert queue == config.rabbitmq_queue and auto_ack is False
            state["gets"] += 1
            return None, None, None

    class Connection:
        is_open = True

        def channel(self):
            return Channel()

        def process_data_events(self, time_limit):
            assert time_limit == 0.1
            if state["index"] == 0:
                assert logs == []
                assert evaluate_alert_rules(metrics=[], logs=logs) == []
            if processor.consumer_lag_active:
                state["index"] += 1
                if state["index"] == 6:
                    # The loop does not observe the stopped state between these calls.
                    processor.set_consumer_lag(False)
                    processor.set_consumer_lag(True, delay_ms=500)
                elif state["index"] == len(observations):
                    processor.set_consumer_lag(False)
            else:
                worker._stop_event.set()

        def close(self):
            self.is_open = False

    monkeypatch.setitem(sys.modules, "pika", SimpleNamespace(
        URLParameters=lambda url: SimpleNamespace(),
        BlockingConnection=lambda params: Connection(),
    ))
    monkeypatch.setattr(notification_app.time, "monotonic", lambda: state["time"])
    monkeypatch.setattr(notification_app.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(notification_app, "emit_structured_log", capture_log)

    def run_with_stale_context():
        set_telemetry_context("prior-correlation", "a" * 32, "b" * 16)
        worker._run_loop()

    Context().run(run_with_stale_context)

    assert state["index"] == len(observations)
    assert state["gets"] == 1
    assert processor.rabbit_backlog_depth == 0
    assert [log["message"] for log in logs] == [
        "Notification consumer backlog detected (depth=2)",
        "Notification consumer backlog detected (depth=4)",
        "Notification consumer backlog detected (depth=5)",
        "Notification consumer backlog detected (depth=6)",
    ]
    for log in logs:
        assert log["severity"] == "WARN"
        assert log["event_type"] == "notification.consumer.lag_backlog"
        assert log["error_code"] == "WARN_QUEUE_CONSUMER_LAG"
        assert log["service_id"] == config.service_id
        assert log["service.name"] == config.service_name
        assert log["environment"] == config.environment
        assert log["build_version"] == config.build_version
        assert log["trace_id"] is None and log["span_id"] is None
        assert log["trace_absent_reason"] == "BACKGROUND_WORKER_NO_ACTIVE_SPAN"
        assert "fault" not in str(log).lower()
        assert "scenario" not in str(log).lower()

    assert evaluate_alert_rules(metrics=[], logs=[]) == []
    alerts = evaluate_alert_rules(metrics=[], logs=logs)
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["alert_type"] == "queue_consumer_lag"
    assert alert["severity"] == "high"
    assert alert["service_id"] == config.service_id
    assert alert["environment"] == config.environment
    assert alert["build_version"] == config.build_version
    assert alert["error_code"] == "WARN_QUEUE_CONSUMER_LAG"
    assert alert["trace_id"] is None
