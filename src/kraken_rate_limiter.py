"""
Centralized, thread-safe rate limiter for Kraken Futures API calls.
Enforces a rolling window limit to prevent 429 errors.
"""
import time
import threading
from collections import deque
from typing import Dict, Any, Optional

class KrakenRateLimiter:
    """
    Centralized, thread-safe rate limiter for Kraken Futures API calls.
    Enforces a rolling window limit.
    
    Kraken Futures API rate limits (approximate):
    - Public endpoints: ~30-60 req/min
    - Private endpoints: ~30 req/min
    - Use conservative limits to stay safe
    """
    def __init__(self, max_calls: int = 60, window_seconds: int = 60, min_delay_seconds: float = 1.0):
        """
        Initialize rate limiter.
        
        Args:
            max_calls: Maximum number of calls allowed in the window (default: 60)
            window_seconds: Rolling window size in seconds (default: 60)
            min_delay_seconds: Minimum delay between calls (default: 1.0s for safety)
        """
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self.min_delay_seconds = min_delay_seconds
        self._calls: deque = deque()
        self._lock = threading.Lock()
        self._last_call_time = 0.0

    def _prune_old_calls(self):
        """Remove calls outside the current window."""
        now = time.time()
        while self._calls and self._calls[0] <= now - self.window_seconds:
            self._calls.popleft()

    def acquire(self):
        """
        Acquire a rate limit slot. Blocks if necessary.
        """
        with self._lock:
            self._prune_old_calls()
            
            # Enforce minimum delay between calls
            elapsed_since_last_call = time.time() - self._last_call_time
            if elapsed_since_last_call < self.min_delay_seconds:
                sleep_for_min_delay = self.min_delay_seconds - elapsed_since_last_call
                time.sleep(sleep_for_min_delay)
                self._last_call_time = time.time()

            # Check if we're over the max calls in the window
            if len(self._calls) >= self.max_calls:
                # Calculate how long to wait until the oldest call expires
                wait_until = self._calls[0] + self.window_seconds
                sleep_time = max(0.0, wait_until - time.time())
                if sleep_time > 0:
                    time.sleep(sleep_time)
                self._prune_old_calls()

            # Record the new call
            self._calls.append(time.time())
            self._last_call_time = time.time()

    def get_stats(self) -> Dict[str, Any]:
        """Return current rate limiter statistics."""
        with self._lock:
            self._prune_old_calls()
            return {
                "calls_in_last_minute": len(self._calls),
                "max_calls_per_minute": self.max_calls,
                "remaining_calls": self.max_calls - len(self._calls),
                "window_seconds": self.window_seconds,
                "min_delay_seconds": self.min_delay_seconds
            }


_kraken_rate_limiter_instance: Optional[KrakenRateLimiter] = None
_kraken_rate_limiter_lock = threading.Lock()


def get_kraken_rate_limiter() -> KrakenRateLimiter:
    """
    Singleton pattern for KrakenRateLimiter.
    
    Kraken Futures API limits (conservative estimates):
    - Public endpoints: ~60 req/min
    - Private endpoints: ~30 req/min
    - Use 1.0s minimum delay for safety
    """
    global _kraken_rate_limiter_instance
    with _kraken_rate_limiter_lock:
        if _kraken_rate_limiter_instance is None:
            _kraken_rate_limiter_instance = KrakenRateLimiter(
                max_calls=60,
                window_seconds=60,
                min_delay_seconds=1.0  # 1.0s delay = 1 req/sec max (60 req/min)
            )
        return _kraken_rate_limiter_instance
