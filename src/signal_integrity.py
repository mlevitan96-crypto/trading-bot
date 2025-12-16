"""
Signal Integrity Module - Status and Health Checks

Provides get_status() function for signal engine health monitoring.
"""

import os
import time
import json
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

# Status colors
STATUS_GREEN = "green"
STATUS_YELLOW = "yellow"
STATUS_RED = "red"


def get_status() -> Dict[str, str]:
    """
    Get signal engine health status.
    
    Returns:
        dict with component -> status_color mapping
        Status colors: "green" (healthy), "yellow" (degraded), "red" (failing)
    """
    status = {}
    
    # Check signal files exist and are recent
    try:
        from src.infrastructure.path_registry import PathRegistry
        
        # Check for signal files
        signal_files = [
            PathRegistry.get_path("logs", "signals.jsonl"),
            PathRegistry.get_path("logs", "ensemble_predictions.jsonl"),
        ]
        
        all_recent = True
        any_missing = False
        
        for signal_file in signal_files:
            if not signal_file.exists():
                any_missing = True
                continue
            
            # Check file age (should be updated within last 10 minutes)
            file_age = time.time() - signal_file.stat().st_mtime
            if file_age > 600:  # 10 minutes
                all_recent = False
        
        if any_missing:
            status["signal_engine"] = STATUS_RED
        elif not all_recent:
            status["signal_engine"] = STATUS_YELLOW
        else:
            status["signal_engine"] = STATUS_GREEN
            
    except Exception as e:
        status["signal_engine"] = STATUS_RED
    
    return status

