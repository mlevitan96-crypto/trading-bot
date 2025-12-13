"""
Phases 8.7–8.9 Expansion Pack — Transparency & Audit, Collaborative Intelligence, External Signal Integration
Unified patch: immutable auditing + cockpit telemetry, multi-bot consensus coordination, and external intelligence confidence filters.
Stacks safely on Phases 8.0–8.6 with strict separation of concerns and no safety regressions.

Contents:
- Phase 8.7 Transparency & Audit:
  * Immutable audit event stream with digest chaining
  * Operator cockpit telemetry: consolidated safety and optimization views
  * Compliance export hooks and minimal REST status provider
- Phase 8.8 Collaborative Intelligence:
  * Peer bot consensus voting to gate promotions and suppress crowding
  * Distributed experiment seeding with quorum-based promotion
  * Conflict and crowding sentinels based on peer overlap and correlation clusters
- Phase 8.9 External Signal Integration:
  * Whale flow, sentiment, and macro overlays as confidence modifiers
  * Signal hygiene: decay, source weighting, and suppression when signals conflict
  * Exposure and routing adjustments gated by validation and regime alignment

Assumptions:
- Prior phases are active (8.0–8.6) and provide scheduler, status providers, telemetry, and safety controls.
- Dashboard & API: emit_dashboard_event, register_status_provider, register_periodic_task.
"""

import time
import json
import hashlib
import threading
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from src.phase87_89_hooks import (
    emit_dashboard_event,
    register_status_provider,
    status_provider_fetch,
    get_peer_bot_snapshot,
    large_positions_symbols,
    rolling_corr_24h,
    freeze_new_entries_global,
    list_all_symbols,
    get_whale_flow_confidence,
    get_sentiment_score,
    get_macro_risk_confidence,
    last_validation_suite_passed,
    current_global_regime_name,
    nudge_symbol_weight
)

_phase87_lock = threading.Lock()
_phase88_lock = threading.Lock()
_phase89_lock = threading.Lock()

def now() -> float:
    return time.time()

def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

@dataclass
class Phase87Config:
    audit_log_path: str = "logs/audit_chain.jsonl"
    cockpit_refresh_sec: int = 60
    export_request_window_min: int = 30

@dataclass
class Phase88Config:
    peer_quorum_min: int = 2
    consensus_threshold: float = 0.67
    max_peer_overlap_pct: float = 0.50
    correlation_cluster_cap: float = 0.65
    cadence_sec: int = 300

@dataclass
class Phase89Config:
    decay_half_life_min: int = 60
    whale_weight: float = 0.4
    sentiment_weight: float = 0.3
    macro_weight: float = 0.3
    conflict_suppress_threshold: float = 0.35
    max_adjust_pct: float = 0.10
    cadence_sec: int = 300

CFG87 = Phase87Config()
CFG88 = Phase88Config()
CFG89 = Phase89Config()

_last_audit_digest: Optional[str] = None
_last_cockpit_payload: Dict = {}
_last_peer_snapshot: Dict = {}
_external_cache: Dict[str, Dict] = {}
_initialized = False

def phase87_append_audit(event_type: str, payload: Dict):
    global _last_audit_digest
    with _phase87_lock:
        record = {
            "ts": now(),
            "event": event_type,
            "payload": payload,
            "prev_digest": _last_audit_digest
        }
        raw = json.dumps(record, sort_keys=True)
        digest = sha256(raw)
        record["digest"] = digest
        try:
            with open(CFG87.audit_log_path, "a") as f:
                f.write(json.dumps(record) + "\n")
            _last_audit_digest = digest
        except Exception as e:
            emit_dashboard_event("phase87_audit_write_error", {"error": str(e)})

def phase87_cockpit_payload() -> Dict:
    val = status_provider_fetch("phase84") or {}
    drift = status_provider_fetch("phase83") or {}
    risk = status_provider_fetch("phase86") or {}
    pred = status_provider_fetch("phase85") or {}
    pack = {
        "validation_history_n": val.get("validation_history_n"),
        "last_regime_change_ts": val.get("last_regime_change_ts"),
        "drift_last_restore_ts": drift.get("last_restore_ts"),
        "baselines": drift.get("baselines"),
        "preserve_until_ts": risk.get("preserve_until_ts"),
        "last_early_warning_ts": pred.get("last_early_warning_ts"),
        "audit_last_digest": _last_audit_digest
    }
    return pack

def phase87_cockpit_tick():
    global _last_cockpit_payload
    with _phase87_lock:
        payload = phase87_cockpit_payload()
        _last_cockpit_payload = payload
        emit_dashboard_event("phase87_cockpit_refresh", payload)

def phase87_export_audit_since(ts_cutoff: float) -> List[Dict]:
    rows = []
    try:
        with open(CFG87.audit_log_path, "r") as f:
            for line in f:
                j = json.loads(line)
                if j.get("ts", 0) >= ts_cutoff:
                    rows.append(j)
    except FileNotFoundError:
        pass
    return rows

def phase88_fetch_peer_signals() -> List[Dict]:
    return get_peer_bot_snapshot()

def phase88_consensus_for_promotion(symbol: str) -> Tuple[bool, float, int]:
    peers = phase88_fetch_peer_signals()
    agree = 0
    total = 0
    for p in peers:
        total += 1
        ps = p.get("promotions", [])
        if any(pr.get("symbol") == symbol for pr in ps):
            agree += 1
    ratio = (agree / total) if total else 0.0
    allowed = (total >= CFG88.peer_quorum_min) and (ratio >= CFG88.consensus_threshold)
    return allowed, ratio, total

def phase88_crowding_guard(symbol: str) -> bool:
    peers = phase88_fetch_peer_signals()
    total_weight = 0.0
    for p in peers:
        for pos in p.get("positions", []):
            if pos["symbol"] == symbol:
                total_weight += pos.get("weight_pct", 0.0)
    return total_weight <= CFG88.max_peer_overlap_pct

def phase88_cluster_corr_guard() -> None:
    peers = phase88_fetch_peer_signals()
    our_syms = large_positions_symbols()
    peer_syms = set()
    for p in peers:
        peer_syms.update([pos["symbol"] for pos in p.get("positions", [])])
    union = list(set(our_syms) | peer_syms)
    
    pairs = []
    for i in range(len(union)):
        for j in range(i+1, len(union)):
            c = rolling_corr_24h(union[i], union[j])
            if c is not None:
                pairs.append(c)
    score = (sum(pairs) / len(pairs)) if pairs else 0.0
    if score >= CFG88.correlation_cluster_cap:
        freeze_new_entries_global()
        emit_dashboard_event("phase88_cluster_corr_guard", {"score": round(score, 2), "symbols": union})

def phase88_consensus_tick():
    global _last_peer_snapshot
    with _phase88_lock:
        snapshot = {"peers": phase88_fetch_peer_signals(), "ts": now()}
        _last_peer_snapshot = snapshot
        emit_dashboard_event("phase88_peer_snapshot", {"peers_n": len(snapshot["peers"])})
        phase88_cluster_corr_guard()

def phase88_gate_promotion(symbol: str, variant: Dict) -> bool:
    safe = phase88_crowding_guard(symbol)
    allowed, ratio, total = phase88_consensus_for_promotion(symbol)
    if not safe:
        emit_dashboard_event("phase88_promotion_blocked_crowding", {"symbol": symbol, "peer_overlap_pct": "exceeds"})
        return False
    if not allowed:
        emit_dashboard_event("phase88_promotion_blocked_consensus", {"symbol": symbol, "ratio": round(ratio,2), "peers": total})
        return False
    emit_dashboard_event("phase88_promotion_consensus_pass", {"symbol": symbol, "ratio": round(ratio,2), "peers": total})
    return True

def phase89_fetch_external(symbols: List[str]) -> Dict[str, Dict[str, float]]:
    data = {}
    for s in symbols:
        data[s] = {
            "whale": get_whale_flow_confidence(s) or 0.5,
            "sentiment": get_sentiment_score(s) or 0.5,
            "macro": get_macro_risk_confidence(s) or 0.5
        }
    return data

def phase89_decay(prev: float, new: float, minutes: float) -> float:
    hl = CFG89.decay_half_life_min
    alpha = 1.0 - 0.5 ** (minutes / hl) if hl > 0 else 1.0
    return prev + alpha * (new - prev)

def phase89_net_confidence(sigs: Dict[str, float]) -> float:
    return (CFG89.whale_weight * sigs.get("whale", 0.5) +
            CFG89.sentiment_weight * sigs.get("sentiment", 0.5) +
            CFG89.macro_weight * sigs.get("macro", 0.5))

def phase89_adjust_exposure(symbol: str, conf: float):
    val_ok = last_validation_suite_passed()
    regime = current_global_regime_name()
    if not val_ok or regime == "risk_off":
        emit_dashboard_event("phase89_skip_gate", {"symbol": symbol, "val_ok": val_ok, "regime": regime})
        return
    
    delta = (conf - 0.5) * 2.0 * CFG89.max_adjust_pct
    if abs(delta) < 0.01:
        return
    nudge_symbol_weight(symbol, delta)
    emit_dashboard_event("phase89_exposure_nudge", {"symbol": symbol, "confidence": round(conf,2), "delta_pct": round(delta,3)})

def phase89_conflict_suppress(sigs: Dict[str, float]) -> bool:
    net = phase89_net_confidence(sigs)
    spread = max(sigs.values()) - min(sigs.values())
    return (spread > 0.4) and (net < CFG89.conflict_suppress_threshold)

def phase89_tick():
    global _external_cache
    with _phase89_lock:
        symbols = list_all_symbols()
        fresh = phase89_fetch_external(symbols)
        for s in symbols:
            prev = _external_cache.get(s, {"ts": now(), **fresh[s]})
            minutes = (now() - prev.get("ts", now())) / 60.0
            blended = {
                "whale": phase89_decay(prev.get("whale", 0.5), fresh[s]["whale"], minutes),
                "sentiment": phase89_decay(prev.get("sentiment", 0.5), fresh[s]["sentiment"], minutes),
                "macro": phase89_decay(prev.get("macro", 0.5), fresh[s]["macro"], minutes)
            }
            if phase89_conflict_suppress(blended):
                emit_dashboard_event("phase89_conflict_suppress", {"symbol": s, "signals": blended})
                _external_cache[s] = {"ts": now(), **blended}
                continue
            conf = phase89_net_confidence(blended)
            phase89_adjust_exposure(s, conf)
            _external_cache[s] = {"ts": now(), **blended}

def phase87_on_any_critical_event(event: str, payload: Dict):
    phase87_append_audit(event, payload)

def phase88_gate_promotion_wrapper(symbol: str, variant: Dict) -> bool:
    return phase88_gate_promotion(symbol, variant)

def get_phase87_status() -> Dict:
    with _phase87_lock:
        return {
            "cockpit": _last_cockpit_payload,
            "audit_last_digest": _last_audit_digest
        }

def get_phase88_status() -> Dict:
    with _phase88_lock:
        return {
            "last_peer_snapshot": _last_peer_snapshot,
            "peer_count": len(_last_peer_snapshot.get("peers", []))
        }

def get_phase89_status() -> Dict:
    with _phase89_lock:
        return {
            "cache_symbols_n": len(_external_cache),
            "sample_signals": {k: v for k, v in list(_external_cache.items())[:3]}
        }

def _restore_audit_state():
    global _last_audit_digest
    try:
        import os
        if not os.path.exists(os.path.dirname(CFG87.audit_log_path)):
            os.makedirs(os.path.dirname(CFG87.audit_log_path), exist_ok=True)
        
        if os.path.exists(CFG87.audit_log_path):
            with open(CFG87.audit_log_path, "r") as f:
                lines = f.readlines()
                if lines:
                    last_record = json.loads(lines[-1])
                    _last_audit_digest = last_record.get("digest")
    except Exception as e:
        emit_dashboard_event("phase87_audit_restore_error", {"error": str(e)})

def initialize_phase87_89():
    global _initialized
    if _initialized:
        return
    
    _restore_audit_state()
    
    register_status_provider("phase87", get_phase87_status)
    register_status_provider("phase88", get_phase88_status)
    register_status_provider("phase89", get_phase89_status)
    
    _initialized = True
    
    emit_dashboard_event("phase87_89_started", {
        "phase87": "Transparency & Audit",
        "phase88": "Collaborative Intelligence",
        "phase89": "External Signal Integration",
        "audit_restored": _last_audit_digest is not None
    })
