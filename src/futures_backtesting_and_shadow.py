# File: futures_backtesting_and_shadow.py
# Purpose: End-to-end backtesting harness + shadow experiments for futures system.
# - Backtesting: Replay historical OHLCV through ENTRY → MONITORING → EXIT (ladder) and produce attribution.
# - Shadow: A/B test multiple configs (EMA spans, tier splits, leverage) on the same data to compare ROI/DD.
#
# Usage:
#   Backtest single config:
#     python3 futures_backtesting_and_shadow.py --backtest --symbol BTCUSDT --ema-short 12 --ema-long 26 \
#       --tiers 0.25,0.25,0.5 --leverage 3 --margin-budget 50 --data data/BTCUSDT_1m.csv
#
#   Run shadow experiments:
#     python3 futures_backtesting_and_shadow.py --shadow --symbol BTCUSDT --data data/BTCUSDT_1m.csv \
#       --configs configs/shadow_configs.json
#
# Expected data format (CSV):
#   timestamp,open,high,low,close,volume
#   ISO8601 or epoch timestamps supported.

import csv
import json
import math
import argparse
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

LOGS = Path("logs")
CONFIGS = Path("configs")
DATA = Path("data")

# ----------------------------------------
# IO helpers
# ----------------------------------------
def load_json(path: Path, fallback=None):
    try:
        with open(path, "r") as f: return json.load(f)
    except: return fallback if fallback is not None else {}

def save_json(path: Path, data: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f: json.dump(data, f, indent=2)

def read_ohlcv_csv(path: Path) -> List[Dict[str, Any]]:
    rows = []
    with open(path, "r") as f:
        r = csv.DictReader(f)
        for row in r:
            rows.append({
                "timestamp": row["timestamp"],
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row.get("volume", 0.0)),
            })
    return rows

# ----------------------------------------
# Math + indicators
# ----------------------------------------
def ema(values: List[float], span: int) -> List[float]:
    if not values: return []
    k = 2 / (span + 1)
    out = [values[0]]
    for i in range(1, len(values)):
        out.append(values[i] * k + out[-1] * (1 - k))
    return out

def atr(high: List[float], low: List[float], close: List[float], period: int = 14) -> List[float]:
    trs = []
    prev_close = close[0]
    for i in range(len(close)):
        tr = max(high[i] - low[i], abs(high[i] - prev_close), abs(low[i] - prev_close))
        trs.append(tr)
        prev_close = close[i]
    out = []
    window = []
    for i in range(len(trs)):
        window.append(trs[i])
        if len(window) > period: window.pop(0)
        out.append(sum(window) / len(window))
    return out

# ----------------------------------------
# Config models
# ----------------------------------------
@dataclass
class StrategyConfig:
    ema_short: int = 12
    ema_long: int = 26
    tiers_pct: List[float] = field(default_factory=lambda: [0.25, 0.25, 0.5])
    rr_targets_pct: List[float] = field(default_factory=lambda: [1.0, 2.0])
    trail_atr_mult: float = 2.0
    leverage: int = 3
    margin_budget_usdt: float = 50.0
    cooldown_s: int = 60
    min_slice: float = 0.001

# ----------------------------------------
# Backtest state + attribution
# ----------------------------------------
@dataclass
class Position:
    side: Optional[str] = None    # "LONG" or "SHORT"
    entry_price: float = 0.0
    qty: float = 0.0
    leverage: int = 1

@dataclass
class AttributionRecord:
    timestamp: str
    symbol: str
    strategy: str
    regime: str
    leverage: int
    roi: float
    pnl: float
    fees: float

# ----------------------------------------
# Core helpers
# ----------------------------------------
def compute_qty(entry_price: float, leverage: int, margin_budget_usdt: float) -> float:
    if entry_price <= 0 or leverage <= 0: return 0.0
    return round((margin_budget_usdt * leverage) / entry_price, 6)

def regime_infer(atr_series: List[float], close: List[float]) -> str:
    # Simple heuristic: ATR relative to price
    if not atr_series or not close: return "unknown"
    rel = atr_series[-1] / max(1e-9, close[-1])
    if rel >= 0.03: return "volatile"
    if rel >= 0.015: return "choppy"
    return "trending"

def signal_from_ema(short: List[float], long: List[float]) -> str:
    return "LONG" if short[-1] > long[-1] else "SHORT"

# ----------------------------------------
# Ladder exit evaluation (backtest)
# ----------------------------------------
def evaluate_ladder_triggers(side: str, entry_price: float, current_price: float,
                             rr_targets_pct: List[float], trail_stop: float) -> List[str]:
    reasons = []
    # RR targets
    for tgt in rr_targets_pct:
        if side == "LONG" and current_price >= entry_price * (1 + tgt / 100.0):
            reasons.append(f"rr_hit_{tgt}%")
            break
        if side == "SHORT" and current_price <= entry_price * (1 - tgt / 100.0):
            reasons.append(f"rr_hit_{tgt}%")
            break
    # Trailing stop
    if (side == "LONG" and current_price <= trail_stop) or (side == "SHORT" and current_price >= trail_stop):
        reasons.append("trail_stop")
    return reasons

def build_trailing_stop(entry_price: float, current_price: float, atr_val: float, side: str, atr_mult: float) -> float:
    if side == "LONG":
        return max(entry_price * 0.4, current_price - atr_mult * atr_val)
    else:
        return min(entry_price * 1.6, current_price + atr_mult * atr_val)

# ----------------------------------------
# Backtesting engine
# ----------------------------------------
def backtest_symbol(symbol: str, ohlcv: List[Dict[str, Any]], cfg: StrategyConfig) -> Dict[str, Any]:
    close = [row["close"] for row in ohlcv]
    high = [row["high"] for row in ohlcv]
    low = [row["low"] for row in ohlcv]
    ts = [row["timestamp"] for row in ohlcv]

    short_ema = ema(close, cfg.ema_short)
    long_ema = ema(close, cfg.ema_long)
    atr_series = atr(high, low, close, period=14)

    pos = Position()
    records: List[AttributionRecord] = []
    ladder_fills: List[Dict[str, Any]] = []
    last_trade_index = -999999

    tiers_norm = cfg.tiers_pct
    s = sum(tiers_norm)
    tiers_norm = [p / s for p in tiers_norm]

    for i in range(max(cfg.ema_long, 14), len(close)):
        # infer regime
        regime = regime_infer(atr_series[:i+1], close[:i+1])
        current_price = close[i]
        signal_state = signal_from_ema(short_ema[:i+1], long_ema[:i+1])
        prev_signal_state = signal_from_ema(short_ema[:i], long_ema[:i])

        # Cooldown (index-based)
        if i - last_trade_index < max(1, cfg.cooldown_s // 60):
            pass  # skip gating action

        # Entry/flip logic
        if pos.side is None:
            if signal_state == "LONG" and prev_signal_state == "SHORT":
                qty = compute_qty(current_price, cfg.leverage, cfg.margin_budget_usdt)
                pos = Position("LONG", current_price, qty, cfg.leverage)
                last_trade_index = i
            elif signal_state == "SHORT" and prev_signal_state == "LONG":
                qty = compute_qty(current_price, cfg.leverage, cfg.margin_budget_usdt)
                pos = Position("SHORT", current_price, qty, cfg.leverage)
                last_trade_index = i
        else:
            # signal reversal: plan to execute a ladder slice at reversal
            reversal = (signal_state != prev_signal_state)

            # trailing stop from ATR
            atr_val = atr_series[i]
            tstop = build_trailing_stop(pos.entry_price, current_price, atr_val, pos.side, cfg.trail_atr_mult)

            # RR + trailing triggers
            triggers = evaluate_ladder_triggers(pos.side, pos.entry_price, current_price, cfg.rr_targets_pct, tstop)
            if reversal:
                triggers.append("signal_reverse")

            # Execute slices based on triggers: tier 0 first for rr/reversal, tier 2 for trail_stop
            for t_idx, tier_label in enumerate(["tier0", "tier1", "tier2"][:len(tiers_norm)]):
                # pick reason per tier priority
                reason = None
                if "trail_stop" in triggers and t_idx == len(tiers_norm)-1:
                    reason = "trail_stop"
                elif any(r.startswith("rr_hit_") for r in triggers) and t_idx == 0:
                    reason = [r for r in triggers if r.startswith("rr_hit_")][0]
                elif "signal_reverse" in triggers and t_idx == 1:
                    reason = "signal_reverse"

                if reason:
                    slice_qty = round(pos.qty * tiers_norm[t_idx], 6)
                    if slice_qty >= cfg.min_slice and pos.qty > 0:
                        # close slice
                        pnl = (current_price - pos.entry_price) * slice_qty * (1 if pos.side == "LONG" else -1) * pos.leverage
                        roi = (pnl / max(1e-9, pos.entry_price * slice_qty)) * 100.0
                        records.append(AttributionRecord(
                            timestamp=ts[i], symbol=symbol, strategy="EMA", regime=regime,
                            leverage=pos.leverage, roi=roi, pnl=pnl, fees=0.0
                        ))
                        ladder_fills.append({
                            "timestamp": ts[i], "symbol": symbol, "side": pos.side,
                            "tier_index": t_idx, "tier_pct": round(tiers_norm[t_idx], 2),
                            "qty": slice_qty, "reason": reason, "fill_price": current_price
                        })
                        pos.qty = round(pos.qty - slice_qty, 6)
                        last_trade_index = i

            # if fully exited, reset position
            if pos.qty <= cfg.min_slice:
                pos = Position()

    # Aggregate stats
    total_pnl = round(sum(r.pnl for r in records), 6)
    avg_roi = round(sum(r.roi for r in records) / len(records), 6) if records else 0.0
    max_dd = estimate_drawdown(records)

    # Persist backtest report
    report = {
        "symbol": symbol,
        "strategy": "EMA",
        "config": cfg.__dict__,
        "records": [r.__dict__ for r in records],
        "ladder_fills": ladder_fills,
        "total_pnl": total_pnl,
        "avg_roi_pct": avg_roi,
        "max_drawdown_pct": max_dd,
        "generated_at": datetime.utcnow().isoformat()
    }
    save_json(LOGS / f"backtest_{symbol}.json", report)
    return report

def estimate_drawdown(records: List[AttributionRecord]) -> float:
    # Simple equity curve DD estimate from PnL; treat cumulative ROI as equity proxy
    equity = 100.0
    peak = equity
    max_dd = 0.0
    for r in records:
        equity *= (1.0 + r.roi / 100.0)
        peak = max(peak, equity)
        dd = (peak - equity) / peak * 100.0
        max_dd = max(max_dd, dd)
    return round(max_dd, 4)

# ----------------------------------------
# Shadow experiments
# ----------------------------------------
def run_shadow(symbol: str, ohlcv: List[Dict[str, Any]], configs_path: Path) -> Dict[str, Any]:
    cfgs = load_json(configs_path, {"experiments": []}).get("experiments", [])
    results = []
    for c in cfgs:
        cfg = StrategyConfig(
            ema_short=int(c.get("ema_short", 12)),
            ema_long=int(c.get("ema_long", 26)),
            tiers_pct=list(c.get("tiers_pct", [0.25, 0.25, 0.5])),
            rr_targets_pct=list(c.get("rr_targets_pct", [1.0, 2.0])),
            trail_atr_mult=float(c.get("trail_atr_mult", 2.0)),
            leverage=int(c.get("leverage", 3)),
            margin_budget_usdt=float(c.get("margin_budget_usdt", 50.0)),
            cooldown_s=int(c.get("cooldown_s", 60)),
            min_slice=float(c.get("min_slice", 0.001)),
        )
        rep = backtest_symbol(symbol, ohlcv, cfg)
        results.append({
            "name": c.get("name", f"cfg_{len(results)}"),
            "ema_short": cfg.ema_short,
            "ema_long": cfg.ema_long,
            "tiers_pct": cfg.tiers_pct,
            "leverage": cfg.leverage,
            "trail_atr_mult": cfg.trail_atr_mult,
            "total_pnl": rep["total_pnl"],
            "avg_roi_pct": rep["avg_roi_pct"],
            "max_drawdown_pct": rep["max_drawdown_pct"]
        })

    # Rank by net performance with DD penalty
    ranked = sorted(results, key=lambda x: (x["avg_roi_pct"] - 0.5 * x["max_drawdown_pct"]), reverse=True)
    out = {
        "symbol": symbol,
        "ranked": ranked,
        "generated_at": datetime.utcnow().isoformat()
    }
    save_json(LOGS / f"shadow_{symbol}.json", out)
    return out

# ----------------------------------------
# CLI
# ----------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Futures backtesting + shadow experiments")
    parser.add_argument("--backtest", action="store_true", help="Run backtest for single config")
    parser.add_argument("--shadow", action="store_true", help="Run shadow experiments")
    parser.add_argument("--symbol", type=str, default="BTCUSDT")
    parser.add_argument("--data", type=str, required=True, help="Path to OHLCV CSV")
    parser.add_argument("--ema-short", type=int, default=12)
    parser.add_argument("--ema-long", type=int, default=26)
    parser.add_argument("--tiers", type=str, default="0.25,0.25,0.5")
    parser.add_argument("--rr-targets", type=str, default="1.0,2.0")
    parser.add_argument("--trail-atr-mult", type=float, default=2.0)
    parser.add_argument("--leverage", type=int, default=3)
    parser.add_argument("--margin-budget", type=float, default=50.0)
    parser.add_argument("--cooldown", type=int, default=60)
    parser.add_argument("--min-slice", type=float, default=0.001)
    parser.add_argument("--configs", type=str, help="Path to shadow configs JSON")
    args = parser.parse_args()

    ohlcv = read_ohlcv_csv(Path(args.data))

    if args.backtest:
        cfg = StrategyConfig(
            ema_short=args.ema_short,
            ema_long=args.ema_long,
            tiers_pct=[float(x) for x in args.tiers.split(",")],
            rr_targets_pct=[float(x) for x in args.rr_targets.split(",")],
            trail_atr_mult=args.trail_atr_mult,
            leverage=args.leverage,
            margin_budget_usdt=args.margin_budget,
            cooldown_s=args.cooldown,
            min_slice=args.min_slice
        )
        report = backtest_symbol(args.symbol, ohlcv, cfg)
        print(json.dumps(report, indent=2))

    elif args.shadow:
        if not args.configs:
            raise SystemExit("Provide --configs for shadow mode (JSON file with experiments list)")
        result = run_shadow(args.symbol, ohlcv, Path(args.configs))
        print(json.dumps(result, indent=2))

    else:
        print("Specify --backtest or --shadow. See --help for options.")

if __name__ == "__main__":
    main()
