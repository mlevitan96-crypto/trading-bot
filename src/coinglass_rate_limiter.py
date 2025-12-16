#!/usr/bin/env python3
"""
Centralized CoinGlass API Rate Limiter
Ensures we never exceed 30 requests/minute (Hobbyist plan limit).

This module provides a thread-safe rate limiter that tracks all CoinGlass API calls
across the entire application to prevent exceeding the limit.
"""

import time
import threading
from typing import Optional
from collections import deque
from datetime import datetime, timedelta

# Hobbyist plan: 30 requests/minute
COINGLASS_RATE_LIMIT_PER_MINUTE = 30
# Use 2.5s minimum delay to stay safely under limit (60s / 30 = 2.0s, add 25% buffer)
COINGLASS_MIN_DELAY_SECONDS = 2.5
# Track calls in a rolling 60-second window
RATE_LIMIT_WINDOW_SECONDS = 60


class CoinGlassRateLimiter:
    """
    Thread-safe rate limiter for CoinGlass API calls.
    Tracks all calls in a rolling window to ensure we never exceed 30 req/min.
    """
    
    def __init__(self):
        self._lock = threading.RLock()
        self._call_times = deque()  # Timestamps of recent calls
        self._last_call_time = 0.0
        self._total_calls = 0
        self._blocked_calls = 0
    
    def wait_if_needed(self) -> None:
        """
        Wait if necessary to respect rate limits.
        This should be called before every CoinGlass API request.
        """
        with self._lock:
            now = time.time()
            
            # Clean old calls outside the window
            cutoff = now - RATE_LIMIT_WINDOW_SECONDS
            while self._call_times and self._call_times[0] < cutoff:
                self._call_times.popleft()
            
            # Check if we're at the limit
            if len(self._call_times) >= COINGLASS_RATE_LIMIT_PER_MINUTE:
                # Calculate how long to wait
                oldest_call = self._call_times[0]
                wait_time = (oldest_call + RATE_LIMIT_WINDOW_SECONDS) - now + 0.1  # Small buffer
                if wait_time > 0:
                    self._blocked_calls += 1
                    time.sleep(wait_time)
                    # Clean again after waiting
                    now = time.time()
                    cutoff = now - RATE_LIMIT_WINDOW_SECONDS
                    while self._call_times and self._call_times[0] < cutoff:
                        self._call_times.popleft()
            
            # Enforce minimum delay between calls
            elapsed = now - self._last_call_time
            if elapsed < COINGLASS_MIN_DELAY_SECONDS:
                sleep_time = COINGLASS_MIN_DELAY_SECONDS - elapsed
                time.sleep(sleep_time)
                now = time.time()
            
            # Record this call
            self._call_times.append(now)
            self._last_call_time = now
            self._total_calls += 1
    
    def get_stats(self) -> dict:
        """Get current rate limiter statistics."""
        with self._lock:
            now = time.time()
            cutoff = now - RATE_LIMIT_WINDOW_SECONDS
            recent_calls = [t for t in self._call_times if t >= cutoff]
            
            return {
                "calls_in_last_minute": len(recent_calls),
                "max_calls_per_minute": COINGLASS_RATE_LIMIT_PER_MINUTE,
                "total_calls": self._total_calls,
                "blocked_calls": self._blocked_calls,
                "utilization_pct": (len(recent_calls) / COINGLASS_RATE_LIMIT_PER_MINUTE) * 100,
                "headroom": COINGLASS_RATE_LIMIT_PER_MINUTE - len(recent_calls)
            }
    
    def can_make_call(self) -> bool:
        """Check if we can make a call without waiting (for non-blocking checks)."""
        with self._lock:
            now = time.time()
            cutoff = now - RATE_LIMIT_WINDOW_SECONDS
            recent_calls = [t for t in self._call_times if t >= cutoff]
            return len(recent_calls) < COINGLASS_RATE_LIMIT_PER_MINUTE


# Global singleton instance
_rate_limiter_instance: Optional[CoinGlassRateLimiter] = None
_rate_limiter_lock = threading.Lock()


def get_rate_limiter() -> CoinGlassRateLimiter:
    """Get the global CoinGlass rate limiter instance."""
    global _rate_limiter_instance
    if _rate_limiter_instance is None:
        with _rate_limiter_lock:
            if _rate_limiter_instance is None:
                _rate_limiter_instance = CoinGlassRateLimiter()
    return _rate_limiter_instance


def wait_for_rate_limit():
    """
    Convenience function to wait for rate limit before making a CoinGlass API call.
    Use this before every CoinGlass API request.
    """
    get_rate_limiter().wait_if_needed()

