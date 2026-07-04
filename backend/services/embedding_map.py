"""Generate WizMap-compatible data from Qdrant log_clusters embeddings."""

from __future__ import annotations

import html
import json
import logging
import os
import time
from typing import Any

# Disable numba's on-disk JIT cache — it fails when running as non-root in
# slim containers ("no locator available for file ...").
os.environ.setdefault("NUMBA_CACHE_DIR", "/tmp/numba_cache")
os.environ.setdefault("NUMBA_DISABLE_JIT", "0")

import numpy as np
from core.settings import get_settings

logger = logging.getLogger(__name__)

MAX_POINTS = 2000
CACHE_TTL_SEC = 120

_cache: dict[str, Any] = {
    "data_ndjson": "",
    "grid_json": "",
    "count": 0,
    "generated_at": 0.0,
}


def _scroll_clusters(qdrant_client: Any, collection: str) -> list[dict[str, Any]]:
    """Scroll all cluster points (with vectors) from Qdrant."""
    all_records: list[dict[str, Any]] = []
    offset = None
    while len(all_records) < MAX_POINTS:
        records, next_offset = qdrant_client.scroll(
            collection_name=collection,
            limit=min(500, MAX_POINTS - len(all_records)),
            offset=offset,
            with_payload=True,
            with_vectors=True,
        )
        if not records:
            break
        for r in records:
            payload = r.payload or {}
            vector = r.vector
            if vector is None:
                continue
            all_records.append({"payload": payload, "vector": vector})
        if next_offset is None:
            break
        offset = next_offset
    return all_records


def _build_label(payload: dict[str, Any]) -> str:
    representative = str(payload.get("representative_log") or payload.get("message") or "")
    count = int(payload.get("occurrence_count") or 1)
    service = payload.get("service_name") or payload.get("service_id") or "unknown"
    label = payload.get("cluster_label") or payload.get("cluster_summary") or representative[:60]
    return f"[{service}] ({count}x) {label}"


def _escape_html(text: str) -> str:
    return html.escape(text, quote=False)


def _build_tooltip(payload: dict[str, Any]) -> str:
    representative = str(payload.get("representative_log") or payload.get("message") or "")
    count = int(payload.get("occurrence_count") or 1)
    service = str(payload.get("service_name") or payload.get("service_id") or "unknown")
    samples = [str(s) for s in (payload.get("sample_logs") or []) if s]
    if not samples and representative:
        samples = [representative]
    sample_lines = "<br>".join(
        f"&nbsp;&nbsp;• {_escape_html(s[:200])}" for s in samples[:5]
    )
    more = ""
    if len(samples) > 5:
        more = f"<br>&nbsp;&nbsp;… +{len(samples) - 5} more"
    return (
        f"<b>{_escape_html(representative[:120])}</b><br>"
        f"Service: {_escape_html(service)}<br>"
        f"Occurrences: {count}<br>"
        f"<br><b>Sample logs:</b><br>{sample_lines}{more}"
    )


def _compute_wizmap_payload(qdrant_client: Any) -> dict[str, Any]:
    settings = get_settings()
    clusters_collection = settings.qdrant_cluster_collection

    records = _scroll_clusters(qdrant_client, clusters_collection)
    if not records:
        return {"data_ndjson": "", "grid_json": "", "count": 0}

    embeddings = np.array([r["vector"] for r in records], dtype=np.float32)
    if len(embeddings) <= 2:
        coords = np.array([[float(i), 0.0] for i in range(len(embeddings))], dtype=np.float32)
    else:
        n_neighbors = min(15, len(embeddings) - 1)
        reducer = __import__("umap").UMAP(
            n_components=2,
            n_neighbors=max(2, n_neighbors),
            min_dist=0.1,
            metric="cosine",
            random_state=42,
        )
        coords = reducer.fit_transform(embeddings)

    labels: list[str] = []
    tooltips: list[str] = []
    xs: list[float] = []
    ys: list[float] = []

    for i, r in enumerate(records):
        payload = r["payload"]
        xs.append(float(coords[i][0]))
        ys.append(float(coords[i][1]))
        labels.append(_build_label(payload))
        tooltips.append(_build_tooltip(payload))

    import wizmap

    # WizMap hover shows the 3rd NDJSON column as tooltip; grid topics use short labels.
    data_list = wizmap.generate_data_list(xs, ys, tooltips)
    grid_dict = wizmap.generate_grid_dict(
        xs,
        ys,
        labels,
        embedding_name="Logara Log Clusters",
        grid_size=80,
    )

    data_ndjson = "\n".join(json.dumps(row) for row in data_list)
    grid_json = json.dumps(grid_dict)

    return {
        "data_ndjson": data_ndjson,
        "grid_json": grid_json,
        "count": len(xs),
    }


def get_wizmap_bundle(qdrant_client: Any, *, force_refresh: bool = False) -> dict[str, Any]:
    """Return cached WizMap data/grid strings (recomputed every CACHE_TTL_SEC)."""
    now = time.time()
    if (
        not force_refresh
        and _cache.get("generated_at", 0) > 0
        and (now - _cache["generated_at"]) < CACHE_TTL_SEC
    ):
        return _cache

    payload = _compute_wizmap_payload(qdrant_client)
    _cache.update(payload)
    _cache["generated_at"] = now
    return _cache


def generate_wizmap_data(qdrant_client: Any) -> dict[str, Any]:
    """Return summary + raw strings for JSON API consumers."""
    bundle = get_wizmap_bundle(qdrant_client)
    return {
        "data": bundle["data_ndjson"],
        "grid": bundle["grid_json"],
        "count": bundle["count"],
    }
