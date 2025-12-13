"""
Phase 2 Telemetry - Comprehensive logging and metrics emission.

Tracks all Phase 2 gates, decisions, and performance metrics with
detailed audit trails for debugging and validation.
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
from collections import Counter, deque


class Phase2Telemetry:
    """Comprehensive Phase 2 telemetry and logging."""
    
    def __init__(self, log_dir: str = "logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        
        # Log files
        self.audit_log_file = self.log_dir / "phase2_audit_trail.json"
        self.metrics_file = self.log_dir / "phase2_metrics.json"
        self.promotion_log_file = self.log_dir / "phase2_promotions.json"
        
        # In-memory buffers (for performance)
        self.audit_buffer = deque(maxlen=1000)
        self.block_reasons_counter = Counter()
        self.last_emit_time = datetime.now()
    
    def log_signal_decision(self, audit_trail: Dict):
        """
        Log a signal decision with full audit trail.
        
        Args:
            audit_trail: Complete audit trail from pre-trade validation
        """
        self.audit_buffer.append(audit_trail)
        
        # Track block reasons
        if not audit_trail.get("final_decision", {}).get("allowed", False):
            reasons = audit_trail.get("final_decision", {}).get("block_reasons", [])
            for reason in reasons:
                self.block_reasons_counter[reason] += 1
    
    def log_promotion_attempt(self, symbol: str, decision, metrics):
        """
        Log a promotion gate evaluation.
        
        Args:
            symbol: Symbol being evaluated for promotion
            decision: PromotionDecision object
            metrics: PromotionMetrics object
        """
        entry = {
            "timestamp": datetime.now().isoformat(),
            "symbol": symbol,
            "promoted": decision.promote,
            "fail_reasons": decision.fail_reasons,
            "metrics": vars(metrics)
        }
        
        # Append to promotion log
        promotions = []
        if self.promotion_log_file.exists():
            try:
                with open(self.promotion_log_file) as f:
                    data = json.load(f)
                    promotions = data.get("promotions", [])
            except Exception:
                pass
        
        promotions.append(entry)
        
        # Keep last 100 promotions
        if len(promotions) > 100:
            promotions = promotions[-100:]
        
        with open(self.promotion_log_file, 'w') as f:
            json.dump({"promotions": promotions}, f, indent=2)
    
    def emit_metrics_snapshot(self, cfg):
        """
        Emit comprehensive metrics snapshot.
        
        Called every telemetry_emit_interval_sec to provide
        real-time visibility into Phase 2 operation.
        
        Args:
            cfg: Phase2Config
        """
        now = datetime.now()
        time_since_last_emit = (now - self.last_emit_time).total_seconds()
        
        if time_since_last_emit < cfg.telemetry_emit_interval_sec:
            return  # Not time yet
        
        # Flush audit buffer to disk
        self._flush_audit_buffer()
        
        # Build metrics snapshot
        snapshot = {
            "timestamp": now.isoformat(),
            "config": {
                "shadow_mode": cfg.shadow_mode,
                "mtf_adaptive_relaxation": cfg.mtf_adaptive_relaxation,
                "max_leverage_live": cfg.max_leverage_live
            },
            "blocking": {
                "top_reasons": dict(self.block_reasons_counter.most_common(10)),
                "total_blocks": sum(self.block_reasons_counter.values())
            },
            "audit_buffer_size": len(self.audit_buffer)
        }
        
        # Save metrics
        with open(self.metrics_file, 'w') as f:
            json.dump(snapshot, f, indent=2)
        
        self.last_emit_time = now
    
    def _flush_audit_buffer(self):
        """Flush audit buffer to disk."""
        if not self.audit_buffer:
            return
        
        # Load existing audit log
        audit_entries = []
        if self.audit_log_file.exists():
            try:
                with open(self.audit_log_file) as f:
                    data = json.load(f)
                    audit_entries = data.get("entries", [])
            except Exception:
                pass
        
        # Append buffer
        audit_entries.extend(list(self.audit_buffer))
        
        # Keep last 5000 entries
        if len(audit_entries) > 5000:
            audit_entries = audit_entries[-5000:]
        
        # Save
        with open(self.audit_log_file, 'w') as f:
            json.dump({"entries": audit_entries}, f, indent=2)
        
        self.audit_buffer.clear()
    
    def get_block_summary(self) -> Dict:
        """Get summary of recent blocking activity."""
        return {
            "top_10_reasons": dict(self.block_reasons_counter.most_common(10)),
            "total_blocks": sum(self.block_reasons_counter.values())
        }
    
    def get_recent_audits(self, limit: int = 20) -> List[Dict]:
        """Get most recent audit trails."""
        return list(self.audit_buffer)[-limit:]
    
    def get_promotion_history(self, symbol: Optional[str] = None) -> List[Dict]:
        """
        Get promotion attempt history.
        
        Args:
            symbol: Optional filter by symbol
            
        Returns:
            List of promotion attempts
        """
        if not self.promotion_log_file.exists():
            return []
        
        try:
            with open(self.promotion_log_file) as f:
                data = json.load(f)
                promotions = data.get("promotions", [])
                
                if symbol:
                    promotions = [p for p in promotions if p.get("symbol") == symbol]
                
                return promotions
        except Exception:
            return []
