#!/usr/bin/env python3
"""Demo app that emits logs via the embedded OpenTelemetry Python SDK (OTLP)."""

from __future__ import annotations

import os
import random
import signal
import sys
import time

from opentelemetry._logs import get_logger, set_logger_provider
from opentelemetry._logs.severity import SeverityNumber
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource

INTERVAL_SEC = float(os.environ.get("INTERVAL_SEC", "10"))
SERVICE_NAME = os.environ.get("OTEL_SERVICE_NAME", "inventory-service")
OTLP_ENDPOINT = os.environ.get(
    "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT",
    os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4318"),
).rstrip("/")
if not OTLP_ENDPOINT.endswith("/v1/logs"):
    OTLP_ENDPOINT = f"{OTLP_ENDPOINT}/v1/logs"

SCENARIOS: list[tuple[SeverityNumber, str, str]] = [
    (SeverityNumber.ERROR, "ERROR", "Stock reservation failed for sku-{sku} in warehouse {warehouse}"),
    (SeverityNumber.WARN, "WARN", "Low stock threshold reached for sku-{sku}: {units} units left"),
    (SeverityNumber.INFO, "INFO", "Inventory sync completed for region {region} ({count} SKUs)"),
    (SeverityNumber.ERROR, "ERROR", "Upstream catalog API timeout after {seconds}s"),
    (SeverityNumber.WARN, "WARN", "Duplicate reservation request for order ord-{order_id}"),
    (SeverityNumber.INFO, "INFO", "Reserved {units} units of sku-{sku} for order ord-{order_id}"),
]


def build_resource() -> Resource:
    return Resource.create(
        {
            "service.name": SERVICE_NAME,
            "deployment.environment": os.environ.get("DEPLOYMENT_ENV", "demo"),
        }
    )


def setup_otel_logging() -> LoggerProvider:
    logger_provider = LoggerProvider(resource=build_resource())
    set_logger_provider(logger_provider)

    exporter = OTLPLogExporter(endpoint=OTLP_ENDPOINT)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
    return logger_provider


def format_message(template: str) -> str:
    return template.format(
        sku=random.randint(100, 999),
        warehouse=random.choice(["us-east-1", "eu-west-1", "ap-south-1"]),
        units=random.randint(1, 25),
        region=random.choice(["NA", "EU", "APAC"]),
        count=random.randint(50, 500),
        seconds=random.choice([15, 30, 45]),
        order_id=random.randint(10000, 99999),
    )


def emit_demo_log(logger) -> None:
    severity_number, severity_text, template = random.choice(SCENARIOS)
    message = format_message(template)

    logger.emit(
        timestamp=int(time.time() * 1_000_000_000),
        severity_number= ,
        severity_text=severity_text,
        body=message,
        attributes={
            "service_id": SERVICE_NAME,
            "source": "otel-sdk",
        },
    )
    print(
        f" emitted [{severity_text.lower()}] {message} -> {OTLP_ENDPOINT}",
        flush=True,
    )


def main() -> None:
    logger_provider = setup_otel_logging()
    logger = get_logger("logara.demo")

    print(
        f"otel-demo-app started (service.name={SERVICE_NAME}, "
        f"endpoint={OTLP_ENDPOINT}, interval={INTERVAL_SEC}s)",
        flush=True,
    )

    def shutdown(_signum: int, _frame: object) -> None:
        print(" shutting down, flushing OTLP logs...", flush=True)
        logger_provider.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    while True:
        emit_demo_log(logger)
        time.sleep(INTERVAL_SEC)


if __name__ == "__main__":
    main()
