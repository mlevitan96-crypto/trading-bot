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
        
        # Check for signal files - prioritize predictive_signals.jsonl (actual signal source)
        signal_files = [
            PathRegistry.get_path("logs", "predictive_signals.jsonl"),  # Primary signal source
            PathRegistry.get_path("logs", "ensemble_predictions.jsonl"),
        ]
        
        all_recent = True
        any_missing = False
        any_recent = False
        
        for signal_file in signal_files:
            file_path = Path(signal_file)
            if not file_path.exists():
                # Only mark as missing if it's a critical file
                if "predictive_signals.jsonl" in signal_file:
                    any_missing = True
                continue
            
            # Check file age (should be updated within last 10 minutes)
            file_age = time.time() - file_path.stat().st_mtime
            if file_age < 600:  # 10 minutes
                any_recent = True
            else:
                all_recent = False
        
        # More lenient: if ANY file is recent, show green/yellow
        if any_recent:
            status["signal_engine"] = STATUS_GREEN
        elif any_missing and not any_recent:
            status["signal_engine"] = STATUS_RED
        else:
            status["signal_engine"] = STATUS_YELLOW
            
    except Exception as e:
        status["signal_engine"] = STATUS_RED
    
    return status




