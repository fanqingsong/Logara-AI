import json
import pytest
from unittest.mock import patch, MagicMock
from worker import process_log, run_worker

def test_process_log_valid_json(caplog):
    import logging
    caplog.set_level(logging.INFO)
    # Setup
    valid_payload = json.dumps({
        "parsed": {
            "level": "ERROR",
            "message": "Out of memory exception at address 0x1234"
        }
    })
    
    # Execute
    result = process_log(valid_payload)
    
    # Assert
    assert result is True
    assert "Processed ERROR log: Out of memory exception" in caplog.text

def test_process_log_invalid_json(caplog):
    # Setup
    invalid_payload = "{ this is not json"
    
    # Execute
    result = process_log(invalid_payload)
    
    # Assert
    assert result is False
    assert "Failed to parse payload as JSON" in caplog.text

@patch("worker.process_log")
@patch("worker.redis_client.brpop")
def test_run_worker_single_iteration(mock_brpop, mock_process_log):
    # Setup
    # Simulate brpop returning an item once, then simulate KeyboardInterrupt on the second loop to exit
    mock_brpop.side_effect = [
        ("log_queue", '{"test": "data"}'),
        KeyboardInterrupt()
    ]
    
    # Execute
    run_worker()
    
    # Assert
    assert mock_brpop.call_count == 2
    mock_process_log.assert_called_once_with('{"test": "data"}')
