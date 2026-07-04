#!/usr/bin/env python3
"""Write demo JSON log lines for the otel-collector filelog receiver."""

from __future__ import annotations

import json
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path

LOG_FILE = Path(os.environ.get("LOG_FILE", "/var/log/simulator/app.log"))
INTERVAL_SEC = float(os.environ.get("INTERVAL_SEC", "8"))
SERVICE_ID = os.environ.get("SERVICE_ID", "checkout-api")

SCENARIOS: list[tuple[str, str]] = [
    ("error", "Payment gateway timeout: checkout stalled for {seconds}s"),
    ("warn", "Retry attempt {attempt} for order ord-{order_id}"),
    ("info", "Checkout session started for user user-{user_id}"),
    ("error", "Inventory service returned 503 for sku-{sku}"),
    ("warn", "Cart total mismatch detected for order ord-{order_id}"),
    ("info", "Payment authorized for order ord-{order_id} amount={amount}"),
]


def build_record(level: str, message: str) -> dict[str, str]:
    return {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "level": level,
        "service_id": SERVICE_ID,
        "message": message,
    }


def format_message(template: str) -> str:
    return template.format(
        seconds=random.choice([30, 45, 60]),
        attempt=random.randint(1, 3),
        order_id=random.randint(10000, 99999),
        user_id=random.randint(1000, 9999),
        sku=random.randint(100, 999),
        amount=round(random.uniform(19.99, 499.99), 2),
    )


def main() -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.touch(exist_ok=True)

    print(
        f"log-simulator writing to {LOG_FILE} every {INTERVAL_SEC}s "
        f"(service_id={SERVICE_ID})",
        flush=True,
    )

    while True:
        level, template = random.choice(SCENARIOS)
        record = build_record(level, format_message(template))

        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()

        print(f" wrote [{level}] {record['message']}", flush=True)
        time.sleep(INTERVAL_SEC)


if __name__ == "__main__":
    main()
