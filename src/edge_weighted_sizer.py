"""
Edge-Weighted Sizing Module - Scale position size based on signal quality.

This module adjusts position sizes based on:
1. Coin selection grade (A/B/C/D/F)
2. Signal metadata (OFI strength, ensemble confidence, MTF alignment)

The goal is to:
- SIZE UP on high-quality signals (Grade A/B)
- SIZE DOWN on low-quality signals (Grade D/F)
- Log all sizing decisions for learning

Usage:
    from src.edge_weighted_sizer import get_edge_sizer
    
    sizer = get_edge_sizer()
    adjusted_size, multiplier, reason = sizer.compute_size(
        base_size_usd=100.0,
        signal_meta={
            "grade": "A",
            "ofi_score": 0.8,
            "ensemble_score": 0.75,
            "mtf_confidence": 0.9,
            "symbol": "BTCUSDT",
            "side": "LONG"
        }
    )
"""

import json
import os
import fcntl
import time
from datetime import datetime
from typing import Dict, Tuple, Optional, Any
from collections import defaultdict
from pathlib import Path

from src.data_registry import DataRegistry as DR


GRADE_MULTIPLIERS = {
    "A": 1.5,
    "B": 1.2,
    "C": 1.0,
    "D": 0.7,
    "F": 0.5,
}

OFI_THRESHOLDS = {
    "strong": (0.7, 0.15),
    "moderate": (0.5, 0.10),
    "weak": (0.3, 0.05),
}

ENSEMBLE_THRESHOLDS = {
    "high": (0.8, 0.10),
    "medium": (0.6, 0.05),
    "low": (0.4, 0.0),
}

MTF_THRESHOLDS = {
    "aligned": (0.8, 0.10),
    "partial": (0.5, 0.05),
    "conflicting": (0.0, -0.05),
}

MAX_TOTAL_MULTIPLIER = 2.0
MIN_TOTAL_MULTIPLIER = 0.3


def _now() -> str:
    """Get current UTC timestamp in ISO format."""
    return datetime.utcnow().isoformat() + "Z"


def _log(msg: str):
    """Log with timestamp."""
    ts = datetime.utcnow().isoformat() + "Z"
    print(f"[{ts}] [EDGE-SIZER] {msg}")


def _atomic_append_jsonl(path: str, record: Dict[str, Any], timeout: float = 5.0) -> bool:
    """
    Atomically append a record to a JSONL file with file locking.
    
    Args:
        path: Path to JSONL file
        record: Record to append
        timeout: Lock timeout in seconds
        
    Returns:
        True if successful, False otherwise
    """
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        
        lock_path = Path(f"{path}.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(lock_path, 'w') as lock_file:
            start_time = time.time()
            while True:
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except (IOError, OSError):
                    if time.time() - start_time > timeout:
                        _log(f"⚠️ Lock timeout appending to {path}")
                        return False
                    time.sleep(0.05)
            
            try:
                if 'ts' not in record and 'timestamp' not in record:
                    record['ts'] = time.time()
                    record['ts_iso'] = _now()
                
                with open(path, 'a') as f:
                    f.write(json.dumps(record, default=str) + '\n')
                    f.flush()
                    os.fsync(f.fileno())
                return True
            finally:
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                except:
                    pass
                    
    except Exception as e:
        _log(f"⚠️ Error appending to {path}: {e}")
        return False


def _read_jsonl(path: str, last_n: Optional[int] = None) -> list:
    """Read records from a JSONL file."""
    if not os.path.exists(path):
        return []
    
    try:
        records = []
        with open(path, 'r') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        
        if last_n and len(records) > last_n:
            return records[-last_n:]
        return records
    except Exception as e:
        _log(f"⚠️ Error reading {path}: {e}")
        return []


class EdgeWeightedSizer:
    """
    Edge-Weighted Position Sizer.
    
    Adjusts position sizes based on signal quality grade and metadata.
    """
    
    def __init__(self):
        self.sizing_history = defaultdict(list)
        self.stats = {
            "total_decisions": 0,
            "by_grade": defaultdict(int),
            "avg_multiplier": 0.0,
            "total_base_usd": 0.0,
            "total_adjusted_usd": 0.0,
        }
        self._load_recent_stats()
    
    def _load_recent_stats(self):
        """Load recent sizing decisions to initialize stats."""
        try:
            records = _read_jsonl(DR.EDGE_SIZING_LOG, last_n=1000)
            for rec in records:
                grade = rec.get("grade", "C")
                self.stats["by_grade"][grade] += 1
                self.stats["total_decisions"] += 1
                self.stats["total_base_usd"] += rec.get("base_size_usd", 0)
                self.stats["total_adjusted_usd"] += rec.get("final_size_usd", 0)
            
            if self.stats["total_base_usd"] > 0:
                self.stats["avg_multiplier"] = (
                    self.stats["total_adjusted_usd"] / self.stats["total_base_usd"]
                )
            
            _log(f"Loaded {self.stats['total_decisions']} historical sizing decisions")
        except Exception as e:
            _log(f"⚠️ Could not load historical stats: {e}")
    
    def get_grade_multiplier(self, grade: str) -> float:
        """
        Get the base multiplier for a signal quality grade.
        
        Args:
            grade: Signal quality grade (A/B/C/D/F)
            
        Returns:
            Base multiplier for the grade
        """
        return GRADE_MULTIPLIERS.get(grade.upper(), 1.0)
    
    def get_signal_quality_boost(
        self, 
        ofi_score: float, 
        ensemble_score: float, 
        mtf_confidence: float
    ) -> Tuple[float, list]:
        """
        Calculate additional boost based on signal metadata.
        
        Args:
            ofi_score: Order Flow Imbalance score (0-1)
            ensemble_score: Ensemble model confidence (0-1)
            mtf_confidence: Multi-timeframe alignment (0-1)
            
        Returns:
            (boost_amount, reasons_list)
        """
        boost = 0.0
        reasons = []
        
        if ofi_score >= OFI_THRESHOLDS["strong"][0]:
            boost += OFI_THRESHOLDS["strong"][1]
            reasons.append(f"strong_ofi_{ofi_score:.2f}")
        elif ofi_score >= OFI_THRESHOLDS["moderate"][0]:
            boost += OFI_THRESHOLDS["moderate"][1]
            reasons.append(f"moderate_ofi_{ofi_score:.2f}")
        elif ofi_score >= OFI_THRESHOLDS["weak"][0]:
            boost += OFI_THRESHOLDS["weak"][1]
            reasons.append(f"weak_ofi_{ofi_score:.2f}")
        
        if ensemble_score >= ENSEMBLE_THRESHOLDS["high"][0]:
            boost += ENSEMBLE_THRESHOLDS["high"][1]
            reasons.append(f"high_ensemble_{ensemble_score:.2f}")
        elif ensemble_score >= ENSEMBLE_THRESHOLDS["medium"][0]:
            boost += ENSEMBLE_THRESHOLDS["medium"][1]
            reasons.append(f"medium_ensemble_{ensemble_score:.2f}")
        
        if mtf_confidence >= MTF_THRESHOLDS["aligned"][0]:
            boost += MTF_THRESHOLDS["aligned"][1]
            reasons.append(f"mtf_aligned_{mtf_confidence:.2f}")
        elif mtf_confidence >= MTF_THRESHOLDS["partial"][0]:
            boost += MTF_THRESHOLDS["partial"][1]
            reasons.append(f"mtf_partial_{mtf_confidence:.2f}")
        elif mtf_confidence < MTF_THRESHOLDS["conflicting"][0]:
            boost += MTF_THRESHOLDS["conflicting"][1]
            reasons.append(f"mtf_conflicting_{mtf_confidence:.2f}")
        
        return boost, reasons
    
    def compute_size(
        self, 
        base_size_usd: float, 
        signal_meta: Dict[str, Any]
    ) -> Tuple[float, float, str]:
        """
        Compute the adjusted position size based on signal quality.
        
        Args:
            base_size_usd: Base position size in USD
            signal_meta: Signal metadata dict containing:
                - grade: str (A/B/C/D/F)
                - ofi_score: float (0-1)
                - ensemble_score: float (0-1)
                - mtf_confidence: float (0-1)
                - symbol: str
                - side: str (LONG/SHORT)
                
        Returns:
            (adjusted_size_usd, total_multiplier, reason_string)
        """
        grade = signal_meta.get("grade", "C").upper()
        ofi_score = signal_meta.get("ofi_score", 0.5)
        ensemble_score = signal_meta.get("ensemble_score", 0.5)
        mtf_confidence = signal_meta.get("mtf_confidence", 0.5)
        symbol = signal_meta.get("symbol", "UNKNOWN")
        side = signal_meta.get("side", "UNKNOWN")
        
        grade_mult = self.get_grade_multiplier(grade)
        
        boost, boost_reasons = self.get_signal_quality_boost(
            ofi_score, ensemble_score, mtf_confidence
        )
        
        total_multiplier = grade_mult + boost
        
        total_multiplier = max(MIN_TOTAL_MULTIPLIER, min(MAX_TOTAL_MULTIPLIER, total_multiplier))
        
        adjusted_size = base_size_usd * total_multiplier
        
        reasons = [f"grade_{grade}={grade_mult:.2f}x"]
        if boost_reasons:
            reasons.extend(boost_reasons)
        reason_string = " | ".join(reasons)
        
        self.log_decision(
            symbol=symbol,
            side=side,
            base_size=base_size_usd,
            final_size=adjusted_size,
            multiplier=total_multiplier,
            reason=reason_string,
            grade=grade,
            ofi_score=ofi_score,
            ensemble_score=ensemble_score,
            mtf_confidence=mtf_confidence
        )
        
        grade_emoji = {"A": "🔥", "B": "✅", "C": "📊", "D": "⚠️", "F": "🔻"}.get(grade, "❓")
        _log(
            f"{grade_emoji} {symbol} {side}: ${base_size_usd:.2f} → ${adjusted_size:.2f} "
            f"({total_multiplier:.2f}x) [{reason_string}]"
        )
        
        return adjusted_size, total_multiplier, reason_string
    
    def log_decision(
        self,
        symbol: str,
        side: str,
        base_size: float,
        final_size: float,
        multiplier: float,
        reason: str,
        grade: str = "C",
        ofi_score: float = 0.5,
        ensemble_score: float = 0.5,
        mtf_confidence: float = 0.5
    ) -> bool:
        """
        Log a sizing decision to the edge sizing log.
        
        Args:
            symbol: Trading symbol
            side: Trade side (LONG/SHORT)
            base_size: Original base size in USD
            final_size: Adjusted final size in USD
            multiplier: Total multiplier applied
            reason: Reason string for the sizing decision
            grade: Signal quality grade
            ofi_score: OFI score
            ensemble_score: Ensemble confidence
            mtf_confidence: MTF alignment
            
        Returns:
            True if logged successfully
        """
        record = {
            "symbol": symbol,
            "side": side,
            "base_size_usd": base_size,
            "final_size_usd": final_size,
            "multiplier": multiplier,
            "reason": reason,
            "grade": grade,
            "ofi_score": ofi_score,
            "ensemble_score": ensemble_score,
            "mtf_confidence": mtf_confidence,
            "ts": time.time(),
            "ts_iso": _now()
        }
        
        self.stats["total_decisions"] += 1
        self.stats["by_grade"][grade] += 1
        self.stats["total_base_usd"] += base_size
        self.stats["total_adjusted_usd"] += final_size
        if self.stats["total_base_usd"] > 0:
            self.stats["avg_multiplier"] = (
                self.stats["total_adjusted_usd"] / self.stats["total_base_usd"]
            )
        
        return _atomic_append_jsonl(DR.EDGE_SIZING_LOG, record)
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get sizing distribution statistics.
        
        Returns:
            Dict with sizing statistics including:
            - total_decisions: Total number of sizing decisions
            - by_grade: Breakdown by grade (A/B/C/D/F)
            - avg_multiplier: Average multiplier applied
            - grade_distribution: Percentage breakdown by grade
        """
        stats = dict(self.stats)
        stats["by_grade"] = dict(stats["by_grade"])
        
        total = max(1, stats["total_decisions"])
        stats["grade_distribution"] = {
            grade: (count / total) * 100
            for grade, count in stats["by_grade"].items()
        }
        
        stats["generated_at"] = _now()
        
        return stats
    
    def get_recent_decisions(self, last_n: int = 50) -> list:
        """
        Get recent sizing decisions.
        
        Args:
            last_n: Number of recent decisions to return
            
        Returns:
            List of recent sizing decision records
        """
        return _read_jsonl(DR.EDGE_SIZING_LOG, last_n=last_n)
    
    def get_symbol_stats(self, symbol: str, last_n: int = 100) -> Dict[str, Any]:
        """
        Get sizing statistics for a specific symbol.
        
        Args:
            symbol: Trading symbol to filter by
            last_n: Number of recent records to analyze
            
        Returns:
            Statistics for the specified symbol
        """
        records = _read_jsonl(DR.EDGE_SIZING_LOG, last_n=last_n * 10)
        symbol_records = [r for r in records if r.get("symbol") == symbol][-last_n:]
        
        if not symbol_records:
            return {
                "symbol": symbol,
                "decision_count": 0,
                "avg_multiplier": 1.0,
                "grade_distribution": {}
            }
        
        total_mult = sum(r.get("multiplier", 1.0) for r in symbol_records)
        grade_counts = defaultdict(int)
        for r in symbol_records:
            grade_counts[r.get("grade", "C")] += 1
        
        return {
            "symbol": symbol,
            "decision_count": len(symbol_records),
            "avg_multiplier": total_mult / len(symbol_records),
            "grade_distribution": dict(grade_counts),
            "recent_decisions": symbol_records[-5:]
        }


_SIZER_INSTANCE: Optional[EdgeWeightedSizer] = None


def get_edge_sizer() -> EdgeWeightedSizer:
    """
    Get the singleton EdgeWeightedSizer instance.
    
    Returns:
        EdgeWeightedSizer instance
    """
    global _SIZER_INSTANCE
    if _SIZER_INSTANCE is None:
        _SIZER_INSTANCE = EdgeWeightedSizer()
    return _SIZER_INSTANCE


if __name__ == "__main__":
    sizer = get_edge_sizer()
    
    test_cases = [
        {"grade": "A", "ofi_score": 0.85, "ensemble_score": 0.9, "mtf_confidence": 0.85,
         "symbol": "BTCUSDT", "side": "LONG"},
        {"grade": "B", "ofi_score": 0.6, "ensemble_score": 0.7, "mtf_confidence": 0.6,
         "symbol": "ETHUSDT", "side": "SHORT"},
        {"grade": "C", "ofi_score": 0.5, "ensemble_score": 0.5, "mtf_confidence": 0.5,
         "symbol": "SOLUSDT", "side": "LONG"},
        {"grade": "D", "ofi_score": 0.3, "ensemble_score": 0.4, "mtf_confidence": 0.3,
         "symbol": "DOGEUSDT", "side": "LONG"},
        {"grade": "F", "ofi_score": 0.2, "ensemble_score": 0.3, "mtf_confidence": 0.2,
         "symbol": "XRPUSDT", "side": "SHORT"},
    ]
    
    print("\n" + "="*70)
    print("EDGE-WEIGHTED SIZER TEST")
    print("="*70 + "\n")
    
    base_size = 100.0
    for meta in test_cases:
        adjusted, mult, reason = sizer.compute_size(base_size, meta)
        print(f"  {meta['symbol']} Grade {meta['grade']}: ${base_size:.2f} → ${adjusted:.2f}")
        print(f"    Reason: {reason}\n")
    
    print("\n" + "="*70)
    print("SIZING STATS")
    print("="*70)
    stats = sizer.get_stats()
    print(json.dumps(stats, indent=2))
