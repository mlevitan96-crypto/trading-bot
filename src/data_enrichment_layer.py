# === Data Enrichment Layer (src/data_enrichment_layer.py) ===
# Purpose:
# - Join signals with outcomes to create enriched decision records
# - Provide complete context for auto-tuner replay and counterfactual analysis
# - Sustainable data pipeline that doesn't break existing systems
#
# Data Flow:
#   strategy_signals.jsonl (signal context: OFI, ensemble, ROI)
#       +
#   executed_trades.jsonl (outcomes: P&L, fees, win/loss)
#       =
#   enriched_decisions.jsonl (complete records for learning/replay)

import os, json, time
from collections import defaultdict
from src.infrastructure.path_registry import PathRegistry

# Use PathRegistry for absolute path resolution (critical for slot-based deployments)
SIGNALS_LOG = PathRegistry.get_path("logs", "strategy_signals.jsonl")
TRADES_LOG = PathRegistry.get_path("logs", "executed_trades.jsonl")
ENRICHED_LOG = PathRegistry.get_path("logs", "enriched_decisions.jsonl")

def _now(): return int(time.time())

def _read_jsonl(path, limit=500000):
    rows=[]
    # PathRegistry already returns absolute paths, but handle both cases
    if not os.path.exists(path): return rows
    with open(path,"r") as f:
        for line in f:
            line=line.strip()
            if not line: continue
            try: rows.append(json.loads(line))
            except: continue
    return rows[-limit:]

def _append_jsonl(path, row):
    # Ensure directory exists (PathRegistry paths are already absolute)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a") as f: f.write(json.dumps(row) + "\n")

def enrich_recent_decisions(lookback_hours=48):
    """
    Join signals with trade outcomes to create enriched decision records.
    
    Returns: List of enriched records with both signal context and outcomes
    """
    cutoff = _now() - lookback_hours * 3600
    
    # Load signals (has context: OFI, ensemble, ROI, regime, etc)
    signals = _read_jsonl(SIGNALS_LOG, 500000)
    signals = [s for s in signals if int(s.get("ts", 0)) >= cutoff]
    
    # Load predictive signals (has detailed component breakdown: liquidation, funding, whale_flow)
    predictive_signals_path = PathRegistry.get_path("logs", "predictive_signals.jsonl")
    predictive_signals = []
    if os.path.exists(predictive_signals_path):
        predictive_signals = _read_jsonl(str(predictive_signals_path), 500000)
        predictive_signals = [s for s in predictive_signals if int(s.get("ts", 0)) >= cutoff]
    
    # Load trades (has outcomes: P&L, fees, etc)
    trades = _read_jsonl(TRADES_LOG, 500000)
    trades = [t for t in trades if int(t.get("ts", 0)) >= cutoff]
    
    # Index signals by SYMBOL ONLY (not strategy)
    # CRITICAL: OFI signals are shadow (not executed), EMA-Futures executes trades
    # We match by symbol+timestamp to capture signal context regardless of strategy
    signal_index = defaultdict(list)
    for sig in signals:
        key = sig.get("symbol")
        signal_index[key].append(sig)
    
    # Index predictive signals by symbol for component matching
    predictive_index = defaultdict(list)
    for psig in predictive_signals:
        key = psig.get("symbol")
        if key:
            predictive_index[key].append(psig)
    
    # Sort signals by timestamp for efficient matching
    for key in signal_index:
        signal_index[key].sort(key=lambda s: s.get("ts", 0))
    for key in predictive_index:
        predictive_index[key].sort(key=lambda s: s.get("ts", 0))
    
    # Match trades with signals
    enriched = []
    for trade in trades:
        trade_ts = int(trade.get("entry_ts") or trade.get("ts", 0))
        symbol = trade.get("symbol")
        
        # Find signal that occurred just before this trade (within 5 minutes)
        # Match by SYMBOL+TIME only, not by strategy
        matching_signals = signal_index.get(symbol, [])
        signal = None
        
        if matching_signals:
            # Find most recent signal before trade (within 5min window)
            for sig in reversed(matching_signals):
                sig_ts = int(sig.get("ts", 0))
                time_diff = trade_ts - sig_ts
                
                # Signal must be before trade, within 5 minutes
                if 0 <= time_diff <= 300:
                    signal = sig
                    break
        
        # Try to match with predictive signal for detailed component breakdown
        predictive_signal = None
        pred_signals = predictive_index.get(symbol, [])
        if pred_signals:
            for psig in reversed(pred_signals):
                psig_ts = int(psig.get("ts", 0))
                time_diff = trade_ts - psig_ts
                if 0 <= time_diff <= 300:  # Within 5 minutes
                    predictive_signal = psig
                    break
        
        # If no match found, create stub context
        if not signal:
            signal = {
                "_unmatched": True,
                "regime": "unknown",
                "side": trade.get("direction", "UNKNOWN")
            }
        
        # Extract signal context with fallback field names
        # Different strategies use different field names:
        # - Alpha: ofi_score/ofi, ensemble_score/composite
        # - EMA: expected_roi/roi
        ofi_val = float(signal.get("ofi_score") or signal.get("ofi") or signal.get("ofi_value") or 0.0)
        ens_val = float(signal.get("composite") or signal.get("ensemble_score") or signal.get("ensemble") or 0.0)
        roi_val = float(signal.get("expected_roi") or signal.get("roi") or signal.get("roi_threshold") or 0.0)
        
        # Extract signal components from predictive signal if available
        signal_components = {}
        if predictive_signal and predictive_signal.get("signals"):
            pred_signals_dict = predictive_signal.get("signals", {})
            # Extract individual components
            if pred_signals_dict.get("liquidation"):
                liq = pred_signals_dict["liquidation"]
                signal_components["liquidation_cascade"] = {
                    "cascade_active": liq.get("cascade_active", False),
                    "confidence": liq.get("confidence", 0),
                    "direction": liq.get("direction", "NEUTRAL"),
                    "total_1h": liq.get("total_1h", 0),
                }
            if pred_signals_dict.get("funding"):
                funding = pred_signals_dict["funding"]
                signal_components["funding_rate"] = {
                    "rate": funding.get("funding_rate", 0),
                    "confidence": funding.get("confidence", 0),
                    "direction": funding.get("direction", "NEUTRAL"),
                }
            if pred_signals_dict.get("whale_flow"):
                whale = pred_signals_dict["whale_flow"]
                signal_components["whale_flow"] = {
                    "net_flow_usd": whale.get("net_flow_usd", 0),
                    "confidence": whale.get("confidence", 0),
                    "direction": whale.get("direction", "NEUTRAL"),
                }
            if pred_signals_dict.get("oi_velocity"):
                oi_vel = pred_signals_dict["oi_velocity"]
                signal_components["oi_velocity"] = {
                    "change_1h_pct": oi_vel.get("oi_velocity", 0) * 100,
                    "confidence": oi_vel.get("confidence", 0),
                }
            if pred_signals_dict.get("fear_greed"):
                fg = pred_signals_dict["fear_greed"]
                signal_components["fear_greed"] = {
                    "index": fg.get("index", 50),
                    "confidence": fg.get("confidence", 0),
                }
        
        # Fallback: Extract from trade's signal_components if available
        if not signal_components and trade.get("signal_components"):
            signal_components = trade.get("signal_components", {})
        
        # FEE TRACKING FIX: Properly extract fees from multiple possible field names
        fees_usd = trade.get("fees_usd", 0)  # SQLite format
        trading_fees = trade.get("trading_fees", 0)
        funding_fees = trade.get("funding_fees", 0)
        legacy_fees = trade.get("fees", 0)
        
        # Calculate total fees: prefer fees_usd, then sum trading_fees + funding_fees, then legacy "fees"
        if fees_usd and fees_usd != 0:
            total_fees = float(fees_usd)
        elif (trading_fees and trading_fees != 0) or (funding_fees and funding_fees != 0):
            total_fees = float(trading_fees or 0) + float(funding_fees or 0)
        else:
            total_fees = float(legacy_fees or 0.0)
        
        # Create enriched record with BOTH signal context AND outcome
        enriched_record = {
            "ts": trade.get("ts"),
            "symbol": trade.get("symbol"),
            "strategy": (trade.get("strategy_id") or trade.get("strategy", "")).lower(),
            
            # Signal context (for replay) - normalized field names
            "signal_ctx": {
                "ofi": ofi_val,
                "ensemble": ens_val,
                "roi": roi_val,
                "regime": signal.get("regime", "unknown"),
                "side": signal.get("side", trade.get("direction", "UNKNOWN")),
                "_unmatched": signal.get("_unmatched", False),
                # Signal component breakdown (from predictive signals)
                "signal_components": signal_components,
                # Extract volatility/volume if available
                "volatility": trade.get("volatility", signal.get("volatility", 0)),
                "volume": trade.get("volume", trade.get("volume_24h", signal.get("volume", 0))),
            },
            
            # Outcome data (for scoring) - includes proper fee tracking
            "outcome": {
                "pnl_usd": float(trade.get("net_pnl", 0.0) or 0.0),
                "pnl_pct": float(trade.get("pnl_pct", 0.0) or 0.0),
                "fees": total_fees,
                "trading_fees": float(trading_fees or 0),
                "funding_fees": float(funding_fees or 0),
                "entry_price": float(trade.get("entry_price", 0.0) or 0.0),
                "exit_price": float(trade.get("exit_price", 0.0) or 0.0),
                "leverage": float(trade.get("leverage", 1.0) or 1.0)
            },
            
            # Metadata
            "venue": trade.get("venue", "futures"),
            "entry_ts": trade.get("entry_ts", trade.get("ts")),
            "exit_ts": trade.get("exit_ts", trade.get("ts"))
        }
        
        enriched.append(enriched_record)
    
    # Also capture blocked signals (counterfactual opportunity)
    for sig in signals:
        if sig.get("status") == "blocked":
            enriched_record = {
                "ts": sig.get("ts"),
                "symbol": sig.get("symbol"),
                "strategy": (sig.get("strategy_id") or sig.get("strategy", "")).lower(),
                
                "signal_ctx": {
                    "ofi": float(sig.get("ofi_score", 0.0) or 0.0),
                    "ensemble": float(sig.get("composite", 0.0) or 0.0),
                    "roi": float(sig.get("expected_roi", 0.0) or 0.0),
                    "regime": sig.get("regime", "unknown"),
                    "side": sig.get("side", "UNKNOWN")
                },
                
                "outcome": {
                    "executed": False,
                    "block_reason": sig.get("block_reason", "unknown")
                },
                
                "status": "blocked"
            }
            enriched.append(enriched_record)
    
    return enriched

def persist_enriched_data(enriched_records):
    """
    Write enriched records to persistent log for auto-tuner consumption.
    
    CRITICAL: Rewrites the entire file with latest lookback window to prevent duplicates.
    Auto-tuner should only see each trade once.
    """
    # Rewrite file instead of append to prevent duplicates
    with open(ENRICHED_LOG, "w") as f:
        for record in enriched_records:
            f.write(json.dumps(record) + "\n")
    return len(enriched_records)

def run_enrichment_cycle(lookback_hours=48):
    """Run complete enrichment cycle - typically called nightly or on-demand."""
    print(f"🔄 Enriching decisions (last {lookback_hours}h)...")
    
    enriched = enrich_recent_decisions(lookback_hours)
    count = persist_enriched_data(enriched)
    
    print(f"✅ Enriched {count} decision records")
    return {"enriched_count": count, "lookback_hours": lookback_hours}

# For manual testing
if __name__ == "__main__":
    result = run_enrichment_cycle(lookback_hours=48)
    print(f"\nResult: {result}")
