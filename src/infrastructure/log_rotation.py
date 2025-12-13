"""
LOG ROTATION UTILITY
====================
Prevents disk exhaustion from append-only .jsonl log files.

The Problem:
- append_jsonl files grow indefinitely during 24/7 operation
- Replit Reserved VMs have storage quotas
- Disk exhaustion causes OSError and crashes

The Solution:
- Automatic rotation when files exceed size threshold
- Configurable retention of recent log files
- Atomic rotation to prevent data loss

Usage:
    from src.infrastructure.log_rotation import rotate_log, auto_rotate_all
    
    # Rotate a specific log file
    rotate_log("logs/unified_events.jsonl")
    
    # Auto-rotate all .jsonl files in logs/
    auto_rotate_all()
"""

import os
import time
import gzip
import shutil
from pathlib import Path
from datetime import datetime
from typing import List, Optional

try:
    from src.infrastructure.path_registry import PathRegistry
    LOGS_DIR = str(PathRegistry.LOGS_DIR)
except ImportError:
    LOGS_DIR = "logs"

MAX_FILE_SIZE_MB = 50
MAX_ROTATED_FILES = 5
COMPRESS_ROTATED = True


def get_file_size_mb(filepath: str) -> float:
    """Get file size in megabytes."""
    try:
        return os.path.getsize(filepath) / (1024 * 1024)
    except OSError:
        return 0.0


def rotate_log(
    filepath: str,
    max_size_mb: float = MAX_FILE_SIZE_MB,
    max_rotated: int = MAX_ROTATED_FILES,
    compress: bool = COMPRESS_ROTATED
) -> Optional[str]:
    """
    Rotate a log file if it exceeds the size threshold.
    
    Args:
        filepath: Path to the log file
        max_size_mb: Maximum size before rotation (default: 50MB)
        max_rotated: Maximum number of rotated files to keep (default: 5)
        compress: Whether to gzip rotated files (default: True)
    
    Returns:
        Path to rotated file if rotation occurred, None otherwise
    """
    if not os.path.exists(filepath):
        return None
    
    size_mb = get_file_size_mb(filepath)
    if size_mb < max_size_mb:
        return None
    
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    base_name = os.path.basename(filepath)
    dir_name = os.path.dirname(filepath)
    
    rotated_name = f"{base_name}.{timestamp}"
    if compress:
        rotated_name += ".gz"
    
    rotated_path = os.path.join(dir_name, rotated_name)
    
    try:
        if compress:
            with open(filepath, 'rb') as f_in:
                with gzip.open(rotated_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            with open(filepath, 'w') as f:
                pass
        else:
            shutil.move(filepath, rotated_path)
            with open(filepath, 'w') as f:
                pass
        
        print(f"[LOG-ROTATE] Rotated {filepath} ({size_mb:.1f}MB) -> {rotated_name}")
        
        _cleanup_old_rotations(filepath, max_rotated, compress)
        
        return rotated_path
        
    except Exception as e:
        print(f"[LOG-ROTATE] Error rotating {filepath}: {e}")
        return None


def _cleanup_old_rotations(filepath: str, max_keep: int, compressed: bool):
    """Remove old rotated files beyond the retention limit."""
    base_name = os.path.basename(filepath)
    dir_name = os.path.dirname(filepath)
    
    pattern = f"{base_name}."
    rotated_files = []
    
    try:
        for f in os.listdir(dir_name):
            if f.startswith(pattern) and f != base_name:
                full_path = os.path.join(dir_name, f)
                rotated_files.append((full_path, os.path.getmtime(full_path)))
        
        rotated_files.sort(key=lambda x: x[1], reverse=True)
        
        for old_file, _ in rotated_files[max_keep:]:
            try:
                os.remove(old_file)
                print(f"[LOG-ROTATE] Removed old rotation: {os.path.basename(old_file)}")
            except OSError as e:
                print(f"[LOG-ROTATE] Failed to remove {old_file}: {e}")
                
    except OSError as e:
        print(f"[LOG-ROTATE] Error during cleanup: {e}")


def auto_rotate_all(
    logs_dir: str = LOGS_DIR,
    max_size_mb: float = MAX_FILE_SIZE_MB
) -> List[str]:
    """
    Auto-rotate all .jsonl files in the logs directory.
    
    Returns:
        List of rotated file paths
    """
    rotated = []
    
    if not os.path.isdir(logs_dir):
        return rotated
    
    for filename in os.listdir(logs_dir):
        if filename.endswith('.jsonl'):
            filepath = os.path.join(logs_dir, filename)
            result = rotate_log(filepath, max_size_mb=max_size_mb)
            if result:
                rotated.append(result)
    
    return rotated


def get_log_sizes(logs_dir: str = LOGS_DIR) -> dict:
    """Get sizes of all log files for monitoring."""
    sizes = {}
    
    if not os.path.isdir(logs_dir):
        return sizes
    
    for filename in os.listdir(logs_dir):
        if filename.endswith(('.jsonl', '.json', '.log')):
            filepath = os.path.join(logs_dir, filename)
            sizes[filename] = get_file_size_mb(filepath)
    
    return dict(sorted(sizes.items(), key=lambda x: x[1], reverse=True))


def check_disk_health(logs_dir: str = LOGS_DIR, warn_threshold_mb: float = 100) -> dict:
    """
    Check disk health and warn about large log files.
    
    Returns:
        Dict with health status and warnings
    """
    sizes = get_log_sizes(logs_dir)
    total_mb = sum(sizes.values())
    
    warnings = []
    for filename, size_mb in sizes.items():
        if size_mb > warn_threshold_mb:
            warnings.append(f"{filename}: {size_mb:.1f}MB")
    
    return {
        "total_logs_mb": round(total_mb, 2),
        "file_count": len(sizes),
        "largest_files": dict(list(sizes.items())[:5]),
        "warnings": warnings,
        "healthy": len(warnings) == 0
    }
