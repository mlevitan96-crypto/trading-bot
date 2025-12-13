"""
GRACEFUL SHUTDOWN MANAGER
=========================
Provides coordinated shutdown for daemon threads to prevent data corruption.

The Problem:
- Python daemon threads (daemon=True) are abruptly terminated when main thread exits
- This can cause file corruption if a thread was mid-write
- SIGTERM/SIGINT signals kill the process without giving threads cleanup time

The Solution:
- Central shutdown_event that all threads can check
- Grace period for threads to complete current operations
- Protection for critical sections (file writes)

Usage:
    from src.infrastructure.shutdown_manager import (
        shutdown_event, 
        register_cleanup, 
        protected_write,
        wait_for_shutdown
    )
    
    # In your thread loop:
    while not shutdown_event.is_set():
        # do work
        shutdown_event.wait(60)  # sleep with interruptibility
    
    # For protected file writes:
    with protected_write():
        with open(path, 'w') as f:
            f.write(data)
"""

import os
import sys
import time
import signal
import threading
import atexit
from contextlib import contextmanager
from typing import Callable, List

shutdown_event = threading.Event()

_cleanup_handlers: List[Callable] = []
_write_lock = threading.Lock()
_active_writes = 0
_active_writes_lock = threading.Lock()

GRACE_PERIOD_SECONDS = 10


def register_cleanup(handler: Callable):
    """Register a cleanup function to run on shutdown."""
    _cleanup_handlers.append(handler)


def _run_cleanup_handlers():
    """Run all registered cleanup handlers."""
    for handler in _cleanup_handlers:
        try:
            handler()
        except Exception as e:
            print(f"[SHUTDOWN] Cleanup handler error: {e}")


def _wait_for_active_writes(timeout: float = 5.0):
    """Wait for any active protected writes to complete."""
    start = time.time()
    while time.time() - start < timeout:
        with _active_writes_lock:
            if _active_writes == 0:
                return True
        time.sleep(0.1)
    return False


@contextmanager
def protected_write():
    """
    Context manager for protected file writes.
    Prevents shutdown from interrupting critical write operations.
    
    Usage:
        with protected_write():
            with open(path, 'w') as f:
                json.dump(data, f)
    """
    global _active_writes
    with _active_writes_lock:
        _active_writes += 1
    try:
        yield
    finally:
        with _active_writes_lock:
            _active_writes -= 1


def graceful_shutdown(signum=None, frame=None):
    """
    Initiate graceful shutdown sequence.
    Called by signal handlers or manually.
    """
    signal_name = signal.Signals(signum).name if signum else "MANUAL"
    print(f"\n[SHUTDOWN] Received {signal_name}, initiating graceful shutdown...")
    
    shutdown_event.set()
    
    print(f"[SHUTDOWN] Waiting up to {GRACE_PERIOD_SECONDS}s for active writes to complete...")
    if _wait_for_active_writes(GRACE_PERIOD_SECONDS):
        print("[SHUTDOWN] All active writes completed.")
    else:
        print("[SHUTDOWN] Warning: Some writes may still be in progress.")
    
    print("[SHUTDOWN] Running cleanup handlers...")
    _run_cleanup_handlers()
    
    print("[SHUTDOWN] Graceful shutdown complete.")


def wait_for_shutdown(timeout: float = None) -> bool:
    """
    Wait for shutdown event with optional timeout.
    Returns True if shutdown was signaled, False if timeout.
    
    Usage in thread loops:
        while not wait_for_shutdown(60):
            # do periodic work
    """
    return shutdown_event.wait(timeout)


def is_shutting_down() -> bool:
    """Check if shutdown has been initiated."""
    return shutdown_event.is_set()


def setup_signal_handlers():
    """
    Setup signal handlers for graceful shutdown.
    Call this early in the main process.
    """
    try:
        signal.signal(signal.SIGTERM, graceful_shutdown)
        signal.signal(signal.SIGINT, graceful_shutdown)
        print("[SHUTDOWN-MGR] Signal handlers registered (SIGTERM, SIGINT)")
    except ValueError:
        print("[SHUTDOWN-MGR] Warning: Could not register signal handlers (not main thread)")


atexit.register(_run_cleanup_handlers)
