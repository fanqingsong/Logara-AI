from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Union, Optional
from utils.parser import LogParser

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

# --- Pydantic Validation Schemas ---

class SingleLogPayload(BaseModel):
    """Blueprint for a single structured log entry"""
    log_data: str = Field(..., description="The raw text log line")
    source: Optional[str] = Field("unknown", description="The service or module that sent the log")

class BatchIngestionRequest(BaseModel):
    """Blueprint accepting either a single raw text string OR a batch list of structured items"""
    payload: Union[str, List[SingleLogPayload]]

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"payload": "2026-05-21 10:15:00 [ERROR] Connection timed out"},
                {
                    "payload": [
                        {"log_data": "[INFO] System healthy", "source": "auth-service"},
                        {"log_data": "[ERROR] Query failed", "source": "db-pool"}
                    ]
                }
            ]
        }
    }

@app.get("/")
async def root():
    return {"message": "Welcome to Logara AI API", "status": "active"}

@app.post("/ingest")
async def ingest_logs(request: BatchIngestionRequest):
    """
    Ingests logs with validation. Supports backward-compatible raw strings
    as well as list-based structured batches.
    """
    # Case A: If input is a raw string (Backward Compatibility Mode)
    if isinstance(request.payload, str):
        log_str = request.payload.strip()
        if not log_str:
            raise HTTPException(status_code=400, detail="Log message cannot be empty")
            
        parsed = LogParser.parse_line(log_str)
        if not parsed:
            return {"status": "accepted_raw", "message": log_str}
            
        metadata = LogParser.extract_metadata(parsed["message"])
        return {
            "status": "success",
            "parsed": parsed,
            "metadata": metadata
        }

    # Case B: If input is a Batch List (The New Feature!)
    elif isinstance(request.payload, list):
        if len(request.payload) == 0:
            raise HTTPException(status_code=400, detail="Batch log list cannot be empty")

        results = []
        for item in request.payload:
            log_str = item.log_data.strip()
            if not log_str:
                results.append({"status": "failed", "detail": "Empty log entry in batch", "source": item.source})
                continue

            parsed = LogParser.parse_line(log_str)
            if not parsed:
                results.append({"status": "accepted_raw", "message": log_str, "source": item.source})
                continue

            metadata = LogParser.extract_metadata(parsed["message"])
            results.append({
                "status": "success",
                "parsed": parsed,
                "metadata": metadata,
                "source": item.source
            })

        return {
            "status": "batch_success",
            "processed_count": len(results),
            "results": results
        }