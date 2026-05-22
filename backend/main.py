import os
import json
import threading
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from typing import List, Union, Optional
from utils.parser import LogParser
from utils.otel import parse_otel_log_payload
from utils.queue import redis_client

app = FastAPI(
    title="Logara AI API",
    description="Backend for ingestion and analysis of distributed system logs",
    version="0.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "Welcome to Logara AI API", "status": "active"}

# --- Advanced, Hardened Schemas ---

class SingleLogPayload(BaseModel):
    log_data: str = Field(..., description="The raw log text entry string.")
    source: Optional[str] = Field(default="unknown", description="Origin service source identifier.")

class BatchIngestionRequest(BaseModel):
    # CRITERIA 1: Enforce strict list-based array evaluation BEFORE falling back to a raw string
    payload: Union[List[SingleLogPayload], str] = Field(
        ..., 
        description="Accepts either a structured array of log entry payloads or a single legacy raw string."
    )

    # CRITERIA 2: Guardrail - Explicit validation capping maximum batch sizes
    @field_validator("payload")
    @classmethod
    def validate_batch_size(cls, value):
        if isinstance(value, list) and len(value) > 1000:
            raise ValueError("Batch size exceeds safety threshold limit of 1000 log entries per request.")
        return value

# --- Upgraded API Ingestion Endpoint ---

@app.post("/ingest", status_code=status.HTTP_200_OK)
async def ingest_logs(request: BatchIngestionRequest):
    """
    Ingest system logs supporting both modern batch payloads and legacy raw strings.
    
    CRITERIA 3: Returns HTTP 200 OK for partial success resilient batch parsing behavior.
    Explicitly tracks parsing metrics, legacy fallbacks, and execution errors inside the response.
    """
    results = []
    processed_count = 0
    fallback_count = 0
    failed_count = 0

    # Workflow A: Structured Batch List Processing
    if isinstance(request.payload, list):
        if len(request.payload) == 0:
            raise HTTPException(status_code=400, detail="Batch log list cannot be empty")

        for item in request.payload:
            log_str = item.log_data.strip() if item.log_data else ""
            if not log_str:
                results.append({
                    "status": "failed", 
                    "detail": "Empty or malformed log entry in batch", 
                    "source": item.source
                })
                failed_count += 1
                continue

            # Execute real internal engine parsing
            parsed = LogParser.parse_line(log_str)
            if not parsed:
                results.append({
                    "status": "accepted_raw", 
                    "message": log_str, 
                    "source": item.source
                })
                fallback_count += 1
                continue

            metadata = LogParser.extract_metadata(parsed["message"])
            results.append({
                "status": "success",
                "parsed": parsed,
                "metadata": metadata,
                "source": item.source
            })
            processed_count += 1

        return {
            "status": "batch_processed",
            "metrics": {
                "total_received": len(request.payload),
                "successfully_parsed": processed_count,
                "fallback_raw_handled": fallback_count,
                "failed": failed_count
            },
            "results": results
        }

    # Workflow B: Legacy String Fallback Processing
    elif isinstance(request.payload, str):
        log_str = request.payload.strip()
        if not log_str:
            raise HTTPException(status_code=400, detail="Log message cannot be empty")
            
        parsed = LogParser.parse_line(log_str)
        if not parsed:
            return {
                "status": "legacy_success",
                "metrics": {
                    "total_received": 1,
                    "successfully_parsed": 0,
                    "fallback_raw_handled": 1,
                    "failed": 0
                },
                "results": [{"status": "accepted_raw", "message": log_str, "source": "legacy-system"}]
            }
            
        metadata = LogParser.extract_metadata(parsed["message"])
        return {
            "status": "legacy_success",
            "metrics": {
                "total_received": 1,
                "successfully_parsed": 1,
                "fallback_raw_handled": 0,
                "failed": 0
            },
            "results": [{
                "status": "success",
                "parsed": parsed,
                "metadata": metadata,
                "source": "legacy-system"
            }]
        }

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, 
        detail="Payload structured format unparseable."
    )