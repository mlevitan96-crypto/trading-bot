# src/slippage_latency_attribution.py
#
# v5.7 Slippage & Latency Attribution Module
# Purpose: Track execution quality metrics (slippage, latency, fill quality) and attribute them
#          to routing decisions, market conditions, and system changes. Enforce quality gates
#          and trigger routing/config adjustments when execution degrades.
#
# Key behaviors:
# - Aggregates slippage metrics from execution_health.json and executed_trades.jsonl
# - Tracks latency patterns (order submission to fill time)
# - Attributes execution quality to: routing strategy (maker/taker), market regime, venue
# - Computes attribution scores (avg_slippage, p95_latency, partial_fill_rate)
# - Enforces quality gates: adjust routing when slippage exceeds thresholds
# - Writes causal links to knowledge graph for continuous learning
#
# Integration (per 30-min meta-learning cycle):
#   from src.slippage_latency_attribution import SlippageLatencyAttribution
#   sla = SlippageLatencyAttribution()
#   summary = sla.run_cycle()
#   digest["email_body"] += summary["email_body"]
#
# Files used:
# - Reads: logs/execution_health.json, logs/executed_trades.jsonl, logs/learning_updates.jsonl
# - Writes: logs/learning_updates.jsonl, logs/knowledge_graph.jsonl

import os, json, time
from typing import Dict, Any, List, Optional
from collections import defaultdict
from statistics import mean, median

LOGS_DIR = "logs"
os.makedirs(LOGS_DIR, exist_ok=True)

EXEC_HEALTH_LOG        = f"{LOGS_DIR}/execution_health.json"
EXEC_TRADES_LOG        = f"{LOGS_DIR}/executed_trades.jsonl"
LEARNING_UPDATES_LOG   = f"{LOGS_DIR}/learning_updates.jsonl"
KNOWLEDGE_GRAPH_LOG    = f"{LOGS_DIR}/knowledge_graph.jsonl"

# Thresholds
SLIPPAGE_WARN_BPS      = 4.0   # 0.04% = 4 bps warning threshold
SLIPPAGE_CRIT_BPS      = 10.0  # 0.10% = 10 bps critical threshold
LATENCY_WARN_MS        = 500   # 500ms warning
LATENCY_CRIT_MS        = 2000  # 2s critical
PARTIAL_FILL_WARN_PCT  = 10.0  # 10% partial fill rate warning

# Windows
WINDOW_MINS_SHORT = 60   # 1 hour
WINDOW_MINS_LONG  = 240  # 4 hours

def _now(): return int(time.time())

def _append_jsonl(path, obj):
    with open(path, "a") as f: f.write(json.dumps(obj) + "\n")

def _read_jsonl(path, limit=10000):
    rows=[]
    if not os.path.exists(path): return rows
    with open(path, "r") as f:
        for line in f:
            line=line.strip()
            if not line: continue
            try: rows.append(json.loads(line))
            except: continue
    return rows[-limit:]

def _read_json(path, default=None):
    if not os.path.exists(path): return default
    try:
        with open(path, "r") as f: return json.load(f)
    except: return default

def _knowledge_link(subject: Dict[str,Any], predicate: str, obj: Dict[str,Any]):
    _append_jsonl(KNOWLEDGE_GRAPH_LOG, {"ts": _now(), "subject": subject, "predicate": predicate, "object": obj})

class SlippageLatencyAttribution:
    """
    Tracks execution quality metrics and attributes them to routing decisions and market conditions.
    Enforces quality gates and triggers routing adjustments when execution degrades.
    """
    def __init__(self,
                 slippage_warn_bps=SLIPPAGE_WARN_BPS,
                 slippage_crit_bps=SLIPPAGE_CRIT_BPS,
                 latency_warn_ms=LATENCY_WARN_MS,
                 latency_crit_ms=LATENCY_CRIT_MS):
        self.slippage_warn = slippage_warn_bps / 10000.0  # convert bps to decimal
        self.slippage_crit = slippage_crit_bps / 10000.0
        self.latency_warn_ms = latency_warn_ms
        self.latency_crit_ms = latency_crit_ms

    def _get_execution_health_metrics(self) -> Dict[str,Any]:
        """Load recent execution health data"""
        health = _read_json(EXEC_HEALTH_LOG, default={})
        if not health:
            return {"avg_slippage": 0.0, "issue_counts": {}, "events": []}
        return health

    def _get_recent_trades(self, window_mins=WINDOW_MINS_SHORT) -> List[Dict[str,Any]]:
        """Get recent trades within window"""
        cutoff = _now() - (window_mins * 60)
        trades = _read_jsonl(EXEC_TRADES_LOG, limit=5000)
        return [t for t in trades if t.get("ts", 0) >= cutoff]

    def _compute_slippage_stats(self, health_data: Dict[str,Any]) -> Dict[str,Any]:
        """Compute slippage statistics from execution health events"""
        events = health_data.get("events", [])
        if not events:
            return {"avg_slippage_bps": 0.0, "max_slippage_bps": 0.0, "slippage_events": 0}
        
        slippages = [abs(e.get("slippage", 0.0)) for e in events]
        avg_slip = mean(slippages) if slippages else 0.0
        max_slip = max(slippages) if slippages else 0.0
        
        return {
            "avg_slippage_bps": round(avg_slip * 10000, 2),
            "max_slippage_bps": round(max_slip * 10000, 2),
            "slippage_events": len(events),
            "slippage_warnings": health_data.get("issue_counts", {}).get("slippage_warning", 0),
            "slippage_critical": health_data.get("issue_counts", {}).get("slippage_critical", 0)
        }

    def _compute_latency_stats(self, trades: List[Dict[str,Any]]) -> Dict[str,Any]:
        """Compute latency statistics from trade execution times"""
        latencies = []
        for t in trades:
            submit_ts = t.get("submit_ts")
            fill_ts = t.get("ts")
            if submit_ts and fill_ts:
                latency_ms = (fill_ts - submit_ts) * 1000
                latencies.append(latency_ms)
        
        if not latencies:
            return {"avg_latency_ms": 0.0, "p95_latency_ms": 0.0, "latency_samples": 0}
        
        latencies_sorted = sorted(latencies)
        p95_idx = int(len(latencies_sorted) * 0.95)
        
        return {
            "avg_latency_ms": round(mean(latencies), 2),
            "p95_latency_ms": round(latencies_sorted[p95_idx] if latencies_sorted else 0.0, 2),
            "max_latency_ms": round(max(latencies), 2),
            "latency_samples": len(latencies)
        }

    def _compute_fill_quality(self, health_data: Dict[str,Any]) -> Dict[str,Any]:
        """Compute fill quality metrics"""
        events = health_data.get("events", [])
        if not events:
            return {"partial_fills": 0, "tick_misalignments": 0, "total_fills": 0}
        
        issue_counts = health_data.get("issue_counts", {})
        partial_fills = issue_counts.get("partial_fill", 0)
        tick_misalign = issue_counts.get("tick_misalignment", 0)
        
        partial_fill_pct = (partial_fills / len(events) * 100) if events else 0.0
        
        return {
            "partial_fills": partial_fills,
            "tick_misalignments": tick_misalign,
            "total_fills": len(events),
            "partial_fill_pct": round(partial_fill_pct, 2)
        }

    def _attribute_to_routing(self, health_data: Dict[str,Any], trades: List[Dict[str,Any]]) -> Dict[str,Any]:
        """Attribute execution quality to routing decisions (maker vs taker)"""
        maker_slippage = []
        taker_slippage = []
        
        events = health_data.get("events", [])
        event_by_symbol = defaultdict(list)
        for e in events:
            event_by_symbol[e.get("symbol")].append(e)
        
        for t in trades:
            symbol = t.get("symbol")
            is_maker = t.get("is_maker", False)
            if symbol in event_by_symbol and event_by_symbol[symbol]:
                # Match trade to closest execution event
                event = event_by_symbol[symbol][-1]
                slip = abs(event.get("slippage", 0.0))
                if is_maker:
                    maker_slippage.append(slip)
                else:
                    taker_slippage.append(slip)
        
        return {
            "maker_avg_slippage_bps": round(mean(maker_slippage) * 10000, 2) if maker_slippage else 0.0,
            "taker_avg_slippage_bps": round(mean(taker_slippage) * 10000, 2) if taker_slippage else 0.0,
            "maker_samples": len(maker_slippage),
            "taker_samples": len(taker_slippage)
        }

    def _check_quality_gates(self, stats: Dict[str,Any]) -> Dict[str,Any]:
        """Check if execution quality meets gates, propose adjustments"""
        gates = {"passed": True, "warnings": [], "critical": [], "proposed_actions": []}
        
        avg_slip_bps = stats.get("avg_slippage_bps", 0.0)
        max_slip_bps = stats.get("max_slippage_bps", 0.0)
        p95_latency = stats.get("p95_latency_ms", 0.0)
        partial_pct = stats.get("partial_fill_pct", 0.0)
        
        # Slippage gates
        if max_slip_bps >= self.slippage_crit * 10000:
            gates["critical"].append(f"Critical slippage: {max_slip_bps:.2f} bps")
            gates["proposed_actions"].append({
                "action": "reduce_position_sizes",
                "reason": f"slippage {max_slip_bps:.2f} bps exceeds critical threshold"
            })
            gates["passed"] = False
        elif avg_slip_bps >= self.slippage_warn * 10000:
            gates["warnings"].append(f"High average slippage: {avg_slip_bps:.2f} bps")
            gates["proposed_actions"].append({
                "action": "prefer_maker_orders",
                "reason": f"slippage {avg_slip_bps:.2f} bps above warning threshold"
            })
        
        # Latency gates
        if p95_latency >= self.latency_crit_ms:
            gates["critical"].append(f"Critical latency: {p95_latency:.0f} ms")
            gates["proposed_actions"].append({
                "action": "investigate_venue_connection",
                "reason": f"p95 latency {p95_latency:.0f} ms exceeds critical threshold"
            })
            gates["passed"] = False
        elif p95_latency >= self.latency_warn_ms:
            gates["warnings"].append(f"High latency: {p95_latency:.0f} ms")
        
        # Partial fill gates
        if partial_pct >= PARTIAL_FILL_WARN_PCT:
            gates["warnings"].append(f"High partial fills: {partial_pct:.1f}%")
            gates["proposed_actions"].append({
                "action": "adjust_order_sizes",
                "reason": f"partial fill rate {partial_pct:.1f}% exceeds threshold"
            })
        
        return gates

    def run_cycle(self) -> Dict[str,Any]:
        """
        Main cycle: analyze execution quality, attribute to routing/conditions, enforce gates.
        Returns summary with email body.
        """
        now = _now()
        health_data = self._get_execution_health_metrics()
        recent_trades = self._get_recent_trades(window_mins=WINDOW_MINS_SHORT)
        
        # Compute stats
        slippage_stats = self._compute_slippage_stats(health_data)
        latency_stats = self._compute_latency_stats(recent_trades)
        fill_quality = self._compute_fill_quality(health_data)
        routing_attrib = self._attribute_to_routing(health_data, recent_trades)
        
        # Combine stats
        stats = {**slippage_stats, **latency_stats, **fill_quality, **routing_attrib}
        
        # Check gates
        gates = self._check_quality_gates(stats)
        
        # Write attribution links to knowledge graph
        if routing_attrib.get("maker_samples", 0) > 0:
            _knowledge_link(
                {"type": "routing_strategy", "route": "maker"},
                "avg_slippage_bps",
                {"value": routing_attrib["maker_avg_slippage_bps"], "ts": now}
            )
        if routing_attrib.get("taker_samples", 0) > 0:
            _knowledge_link(
                {"type": "routing_strategy", "route": "taker"},
                "avg_slippage_bps",
                {"value": routing_attrib["taker_avg_slippage_bps"], "ts": now}
            )
        
        # Log to learning updates
        _append_jsonl(LEARNING_UPDATES_LOG, {
            "ts": now,
            "update_type": "slippage_latency_attribution",
            "stats": stats,
            "gates": gates
        })
        
        # Email body
        email_body = self._format_email_body(stats, gates)
        
        return {
            "ts": now,
            "stats": stats,
            "gates": gates,
            "email_body": email_body
        }

    def _format_email_body(self, stats: Dict[str,Any], gates: Dict[str,Any]) -> str:
        status = "✅ PASS" if gates["passed"] else "⚠️ DEGRADED"
        
        body = f"""
=== Slippage & Latency Attribution ===
Status: {status}

Slippage Metrics:
  Avg: {stats.get('avg_slippage_bps', 0.0):.2f} bps
  Max: {stats.get('max_slippage_bps', 0.0):.2f} bps
  Events: {stats.get('slippage_events', 0)}
  Warnings: {stats.get('slippage_warnings', 0)}
  Critical: {stats.get('slippage_critical', 0)}

Latency Metrics:
  Avg: {stats.get('avg_latency_ms', 0.0):.2f} ms
  P95: {stats.get('p95_latency_ms', 0.0):.2f} ms
  Max: {stats.get('max_latency_ms', 0.0):.2f} ms
  Samples: {stats.get('latency_samples', 0)}

Fill Quality:
  Partial fills: {stats.get('partial_fills', 0)} ({stats.get('partial_fill_pct', 0.0):.1f}%)
  Tick misalignments: {stats.get('tick_misalignments', 0)}
  Total fills: {stats.get('total_fills', 0)}

Routing Attribution:
  Maker avg slippage: {stats.get('maker_avg_slippage_bps', 0.0):.2f} bps ({stats.get('maker_samples', 0)} samples)
  Taker avg slippage: {stats.get('taker_avg_slippage_bps', 0.0):.2f} bps ({stats.get('taker_samples', 0)} samples)
"""
        
        if gates.get("warnings"):
            body += f"\nWarnings:\n"
            for w in gates["warnings"]:
                body += f"  ⚠️  {w}\n"
        
        if gates.get("critical"):
            body += f"\nCritical Issues:\n"
            for c in gates["critical"]:
                body += f"  🚨 {c}\n"
        
        if gates.get("proposed_actions"):
            body += f"\nProposed Actions:\n"
            for a in gates["proposed_actions"]:
                body += f"  → {a['action']}: {a['reason']}\n"
        
        return body

# CLI
if __name__ == "__main__":
    sla = SlippageLatencyAttribution()
    result = sla.run_cycle()
    print(json.dumps(result, indent=2))
