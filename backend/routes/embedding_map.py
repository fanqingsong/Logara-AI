"""Embedding map routes for WizMap visualization."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse, Response

from services.embedding_map import generate_wizmap_data, get_wizmap_bundle


router = APIRouter()


def _get_qdrant_client():
    from integrations.qdrant import qdrant_client

    return qdrant_client


@router.get("/api/embedding-map")
async def get_embedding_map():
    """Return WizMap metadata (count + raw strings for debugging)."""
    try:
        client = _get_qdrant_client()
        return generate_wizmap_data(client)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate embedding map: {str(exc)}",
        ) from exc


@router.get("/api/embedding-map/data")
async def get_embedding_map_data():
    """WizMap data.ndjson — same-origin URL for the embedded widget."""
    try:
        client = _get_qdrant_client()
        bundle = get_wizmap_bundle(client)
        if bundle["count"] == 0:
            raise HTTPException(status_code=404, detail="No cluster embeddings found")
        return PlainTextResponse(
            content=bundle["data_ndjson"],
            media_type="application/x-ndjson",
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate embedding map data: {str(exc)}",
        ) from exc


@router.get("/api/embedding-map/grid")
async def get_embedding_map_grid():
    """WizMap grid.json — same-origin URL for the embedded widget."""
    try:
        client = _get_qdrant_client()
        bundle = get_wizmap_bundle(client)
        if bundle["count"] == 0:
            raise HTTPException(status_code=404, detail="No cluster embeddings found")
        return Response(
            content=bundle["grid_json"],
            media_type="application/json",
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate embedding map grid: {str(exc)}",
        ) from exc
