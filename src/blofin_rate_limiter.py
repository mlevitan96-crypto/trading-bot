"""
Centralized, thread-safe rate limiter for Blofin API calls.
Enforces a rolling window limit to prevent 429 errors.
"""
import time
import threading
from collections import deque
from typing import Dict, Any, Optional

class BlofinRateLimiter:
    """
    Centralized, thread-safe rate limiter for Blofin API calls.
    Enforces a rolling window limit (e.g., 120 requests per minute for market data).
    """
    def __init__(self, max_calls: int = 120, window_seconds: int = 60, min_delay_seconds: float = 0.5):
        """
        Initialize rate limiter.
        
        Args:
            max_calls: Maximum number of calls allowed in the window
            window_seconds: Rolling window size in seconds
            min_delay_seconds: Minimum delay between calls (helps prevent bursts)
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
        Returns the actual sleep time.
        """
        with self._lock:
            self._prune_old_calls()
            
            # Enforce minimum delay between calls
            elapsed_since_last_call = time.time() - self._last_call_time
            if elapsed_since_last_call < self.min_delay_seconds:
                sleep_for_min_delay = self.min_delay_seconds - elapsed_since_last_call
                time.sleep(sleep_for_min_delay)
                self._last_call_time = time.time()  # Update last call time after sleeping

            # Check if we're over the max calls in the window
            if len(self._calls) >= self.max_calls:
                # Calculate how long to wait until the oldest call expires
                wait_until = self._calls[0] + self.window_seconds
                sleep_time = max(0.0, wait_until - time.time())
                if sleep_time > 0:
                    time.sleep(sleep_time)
                self._prune_old_calls()  # Prune again after sleeping

            # Record the new call
            self._calls.append(time.time())
            self._last_call_time = time.time()  # Update last call time after recording

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


_blofin_rate_limiter_instance: Optional[BlofinRateLimiter] = None
_blofin_rate_limiter_lock = threading.Lock()


def get_blofin_rate_limiter() -> BlofinRateLimiter:
    """
    Singleton pattern for BlofinRateLimiter.
    
    Blofin market data API limits:
    - Public endpoints: ~120 req/min (2 req/sec)
    - Use 0.5s minimum delay to stay safely under limit
    """
    global _blofin_rate_limiter_instance
    with _blofin_rate_limiter_lock:
        if _blofin_rate_limiter_instance is None:
            # Blofin public market data: ~120 req/min = 2 req/sec
            # Use 0.5s delay to stay safely under limit with margin
            _blofin_rate_limiter_instance = BlofinRateLimiter(
                max_calls=120,
                window_seconds=60,
                min_delay_seconds=0.5  # 0.5s delay = 2 req/sec max
            )
        return _blofin_rate_limiter_instance

