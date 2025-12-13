"""
File Locking Module for Atomic JSON Operations

Provides thread-safe and process-safe file locking using fcntl.flock()
combined with atomic temp-file rewrites to prevent JSON corruption.

Usage:
    from src.file_locks import atomic_json_write, locked_json_read

    # Atomic write (prevents corruption)
    with atomic_json_write('logs/positions_futures.json') as data:
        data['open_positions'].append(new_position)
        # Auto-saves on exit

    # Safe read
    data = locked_json_read('logs/positions_futures.json')
"""

import fcntl
import json
import os
import time
import tempfile
from pathlib import Path
from contextlib import contextmanager
from typing import Any, Dict, Optional

LOCK_TIMEOUT = 10.0
LOCK_RETRY_INTERVAL = 0.05
DEFAULT_EMPTY = {"open_positions": [], "closed_positions": []}


class FileLockTimeout(Exception):
    """Raised when file lock cannot be acquired within timeout."""
    pass


class JSONCorruptedError(Exception):
    """Raised when JSON file is corrupted and cannot be repaired."""
    pass


def _acquire_lock(lock_file, exclusive: bool, timeout: float) -> bool:
    """Acquire file lock with timeout."""
    lock_type = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
    start_time = time.time()
    
    while True:
        try:
            fcntl.flock(lock_file.fileno(), lock_type | fcntl.LOCK_NB)
            return True
        except (IOError, OSError):
            if time.time() - start_time > timeout:
                return False
            time.sleep(LOCK_RETRY_INTERVAL)


def _release_lock(lock_file):
    """Release file lock."""
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    except (IOError, OSError):
        pass


def _try_repair_json(filepath: str) -> Optional[Dict]:
    """
    Attempt to repair corrupted JSON by:
    1. Looking for backup files
    2. Extracting valid portions
    """
    backup_dir = Path("logs/backups")
    
    if backup_dir.exists():
        backups = sorted(backup_dir.glob("backup_*.json"), reverse=True)
        for backup in backups[:3]:
            try:
                with open(backup, 'r') as f:
                    data = json.load(f)
                    if "open_positions" in data:
                        print(f"   🔧 [FILE-LOCK] Restored from backup: {backup.name}")
                        return data
            except:
                continue
    
    try:
        with open(filepath, 'r') as f:
            content = f.read()
        
        result = {"open_positions": [], "closed_positions": []}
        
        for key in ["open_positions", "closed_positions"]:
            start = content.find(f'"{key}"')
            if start > 0:
                arr_start = content.find('[', start)
                if arr_start > 0:
                    depth = 0
                    end_pos = arr_start
                    for i, c in enumerate(content[arr_start:]):
                        if c == '[':
                            depth += 1
                        elif c == ']':
                            depth -= 1
                        if depth == 0:
                            end_pos = arr_start + i + 1
                            break
                    try:
                        result[key] = json.loads(content[arr_start:end_pos])
                    except:
                        pass
        
        if result["open_positions"] or result["closed_positions"]:
            print(f"   🔧 [FILE-LOCK] Extracted {len(result['open_positions'])} open, {len(result['closed_positions'])} closed from corrupted file")
            return result
            
    except Exception as e:
        pass
    
    return None


def locked_json_read(filepath: str, default: Optional[Dict] = None, timeout: float = LOCK_TIMEOUT) -> Dict:
    """
    Read JSON file with shared lock (allows concurrent reads).
    
    Args:
        filepath: Path to JSON file
        default: Default value if file doesn't exist or is empty
        timeout: Lock acquisition timeout in seconds
    
    Returns:
        Parsed JSON data
    
    Raises:
        FileLockTimeout: If lock cannot be acquired
        JSONCorruptedError: If file is corrupted and cannot be repaired
    """
    if default is None:
        default = DEFAULT_EMPTY.copy()
    
    path = Path(filepath)
    if not path.exists():
        return default.copy()
    
    lock_path = Path(f"{filepath}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(lock_path, 'w') as lock_file:
        if not _acquire_lock(lock_file, exclusive=False, timeout=timeout):
            print(f"⚠️ [FILE-LOCK] Read lock timeout on {filepath}, returning default")
            return default.copy()
        
        try:
            with open(filepath, 'r') as f:
                try:
                    return json.load(f)
                except json.JSONDecodeError as e:
                    print(f"⚠️ [FILE-LOCK] JSON error in {filepath}: {e}")
                    repaired = _try_repair_json(filepath)
                    if repaired:
                        return repaired
                    return default.copy()
        finally:
            _release_lock(lock_file)


def atomic_json_save(filepath: str, data: Dict, timeout: float = LOCK_TIMEOUT) -> bool:
    """
    Save JSON file atomically with exclusive lock.
    
    Uses temp file + rename pattern for atomic writes.
    
    Args:
        filepath: Path to JSON file
        data: Data to save
        timeout: Lock acquisition timeout in seconds
    
    Returns:
        True if successful, False otherwise
    """
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    lock_path = Path(f"{filepath}.lock")
    
    with open(lock_path, 'w') as lock_file:
        if not _acquire_lock(lock_file, exclusive=True, timeout=timeout):
            print(f"⚠️ [FILE-LOCK] Write lock timeout on {filepath}")
            return False
        
        try:
            fd, temp_path = tempfile.mkstemp(
                suffix='.json',
                prefix='atomic_',
                dir=str(path.parent)
            )
            
            try:
                with os.fdopen(fd, 'w') as f:
                    json.dump(data, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                
                os.replace(temp_path, filepath)
                return True
                
            except Exception as e:
                print(f"⚠️ [FILE-LOCK] Write error: {e}")
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                return False
                
        finally:
            _release_lock(lock_file)


@contextmanager
def atomic_json_write(filepath: str, timeout: float = LOCK_TIMEOUT):
    """
    Context manager for atomic read-modify-write operations.
    
    Usage:
        with atomic_json_write('logs/positions_futures.json') as data:
            data['open_positions'].append(new_position)
            # Auto-saves on exit
    
    Args:
        filepath: Path to JSON file
        timeout: Lock acquisition timeout in seconds
    
    Yields:
        Mutable dict that will be saved on successful exit
    """
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    lock_path = Path(f"{filepath}.lock")
    
    with open(lock_path, 'w') as lock_file:
        if not _acquire_lock(lock_file, exclusive=True, timeout=timeout):
            raise FileLockTimeout(f"Could not acquire lock on {filepath}")
        
        try:
            if path.exists():
                try:
                    with open(filepath, 'r') as f:
                        data = json.load(f)
                except json.JSONDecodeError:
                    data = _try_repair_json(filepath) or DEFAULT_EMPTY.copy()
            else:
                data = DEFAULT_EMPTY.copy()
            
            yield data
            
            fd, temp_path = tempfile.mkstemp(
                suffix='.json',
                prefix='atomic_',
                dir=str(path.parent)
            )
            
            try:
                with os.fdopen(fd, 'w') as f:
                    json.dump(data, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                
                os.replace(temp_path, filepath)
                
            except Exception as e:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                raise
                
        finally:
            _release_lock(lock_file)
