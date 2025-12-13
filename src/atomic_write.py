#!/usr/bin/env python3
"""
src/atomic_write.py
Atomic write helper to ensure durable, atomic file writes with fsync.
"""
import os, tempfile

def atomic_write(path, data, mode="w"):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d or ".")
    try:
        with os.fdopen(fd, mode) as f:
            if isinstance(data, (bytes, bytearray)):
                f.write(data)
            elif isinstance(data, str):
                f.write(data)
            else:
                f.write(str(data))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass
