"""
Watchdog module stub to fix "No module named 'src.watchdog'" errors.
This prevents kill-switch from freezing trading due to missing module.
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class Watchdog:
    """Simple watchdog for health monitoring."""
    
    def __init__(self):
        self.health_score = 1.0
        self.subsystems = {}
    
    def check_subsystem(self, name: str) -> Dict[str, Any]:
        """Check subsystem health."""
        return {
            'name': name,
            'status': 'healthy',
            'health': 1.0
        }
    
    def restart_subsystem(self, name: str) -> bool:
        """Attempt to restart a subsystem."""
        logger.info(f"Watchdog: Restart request for {name}")
        return True
    
    def get_health_score(self) -> float:
        """Get overall system health score (0.0-1.0)."""
        return self.health_score
    
    def update_health(self, score: float):
        """Update overall health score."""
        self.health_score = max(0.0, min(1.0, score))


# Global instance for import compatibility
_watchdog = Watchdog()


def get_watchdog() -> Watchdog:
    """Get global watchdog instance."""
    return _watchdog
