"""
Missed Opportunity Replay Engine
Analyzes blocked signals to determine if they would have been profitable.
"""

import json
import datetime
from pathlib import Path
from src.blofin_client import BlofinClient


RELAXED_ROI_THRESHOLD = 0.001  # 0.1%
RELAXED_ENSEMBLE_THRESHOLD = 0.30
SIMULATION_WINDOW_MINUTES = 60  # Simulate holding for 1 hour


def load_blocked_signals():
    """Load blocked signals from missed opportunities log."""
    try:
        with open("logs/missed_opportunities.json", "r") as f:
            data = json.load(f)
            return data.get("missed_trades", [])
    except (FileNotFoundError, json.JSONDecodeError):
        print("⚠️  No missed opportunities file found.")
        return []


def simulate_trade_outcome(symbol, entry_price, hold_minutes=60):
    """
    Simulate trade outcome by fetching recent historical data.
    
    Args:
        symbol: Trading pair
        entry_price: Entry price for the trade
        hold_minutes: How long to hold the position
    
    Returns:
        dict: Simulation results with exit_price, pnl, roi
    """
    blofin = BlofinClient()
    
    try:
        # Fetch recent data to simulate the trade outcome
        df = blofin.fetch_ohlcv(symbol, timeframe="1m", limit=hold_minutes + 10)
        
        if df is None or len(df) < 10:
            return {"success": False, "reason": "Insufficient data"}
        
        # Simulate various exit scenarios
        import pandas as pd
        
        # Ensure we're working with a DataFrame
        if not isinstance(df, pd.DataFrame):
            return {"success": False, "reason": "Invalid data format"}
        
        # Get price series
        if "close" not in df.columns:
            return {"success": False, "reason": "No close price data"}
        
        close_series = pd.Series(df["close"]) if not isinstance(df["close"], pd.Series) else df["close"]
        
        # Simple simulation: take average exit price over the window
        avg_exit = float(close_series.tail(min(hold_minutes, len(close_series))).mean())
        max_price = float(close_series.max())
        min_price = float(close_series.min())
        
        # Calculate metrics
        avg_roi = (avg_exit - entry_price) / entry_price
        max_roi = (max_price - entry_price) / entry_price
        min_roi = (min_price - entry_price) / entry_price
        
        # Estimate fees (0.02% maker + 0.06% taker = 0.08% round trip)
        fee_pct = 0.0008
        net_roi = avg_roi - fee_pct
        
        return {
            "success": True,
            "entry_price": entry_price,
            "avg_exit": avg_exit,
            "max_price": max_price,
            "min_price": min_price,
            "avg_roi": avg_roi,
            "max_roi": max_roi,
            "min_roi": min_roi,
            "net_roi": net_roi,
            "profitable": net_roi > 0
        }
    
    except Exception as e:
        print(f"⚠️  Simulation error for {symbol}: {e}")
        return {"success": False, "reason": str(e)}


def replay_blocked_signals():
    """
    Replay blocked signals to analyze missed opportunities.
    
    Generates a report showing:
    - How many blocked signals would have been profitable
    - Total missed P&L
    - False negative rate
    """
    blocked = load_blocked_signals()
    
    if not blocked:
        print("📊 No blocked signals to replay")
        return
    
    print(f"\n{'='*60}")
    print(f"🔄 Replaying {len(blocked)} Blocked Signals")
    print(f"{'='*60}\n")
    
    replayed = []
    total_missed_pnl = 0.0
    false_negatives = 0
    profitable_count = 0
    
    for i, signal in enumerate(blocked, 1):
        symbol = signal.get("symbol")
        strategy = signal.get("strategy")
        roi = signal.get("predicted_roi", signal.get("roi", 0.0))
        ensemble = signal.get("ensemble_score", 0.0)
        timestamp = signal.get("timestamp", "")
        reason = signal.get("reason", "unknown")
        
        # Only replay signals that meet relaxed thresholds
        if roi < RELAXED_ROI_THRESHOLD or ensemble < RELAXED_ENSEMBLE_THRESHOLD:
            continue
        
        print(f"[{i}/{len(blocked)}] Simulating {symbol} - {strategy}...")
        
        # Estimate entry price (could be from signal or current price)
        entry_price = signal.get("entry_price", signal.get("price", 0))
        
        if entry_price <= 0:
            # Fetch current price as proxy
            try:
                blofin = BlofinClient()
                df = blofin.fetch_ohlcv(symbol, timeframe="1m", limit=5)
                if df is not None and "close" in df.columns:
                    import pandas as pd
                    close_series = pd.Series(df["close"]) if not isinstance(df["close"], pd.Series) else df["close"]
                    entry_price = float(close_series.iloc[-1])
            except:
                continue
        
        # Simulate the trade
        simulated = simulate_trade_outcome(symbol, entry_price, hold_minutes=SIMULATION_WINDOW_MINUTES)
        
        if not simulated.get("success", False):
            continue
        
        # Calculate P&L (assume $500 position size for normalization)
        position_size = 500
        pnl = position_size * simulated["net_roi"]
        total_missed_pnl += pnl
        
        if simulated["profitable"]:
            profitable_count += 1
            false_negatives += 1
        
        replayed.append({
            "symbol": symbol,
            "strategy": strategy,
            "predicted_roi": roi,
            "ensemble_score": ensemble,
            "blocking_reason": reason,
            "entry_price": entry_price,
            "avg_exit": simulated["avg_exit"],
            "realized_roi": simulated["net_roi"],
            "pnl": round(pnl, 2),
            "profitable": simulated["profitable"],
            "timestamp": timestamp
        })
        
        status = "✅ PROFIT" if simulated["profitable"] else "❌ LOSS"
        print(f"   {status} | ROI: {simulated['net_roi']*100:.2f}% | P&L: ${pnl:.2f}")
    
    # Generate summary report
    total_replayed = len(replayed)
    false_negative_rate = (false_negatives / total_replayed * 100) if total_replayed > 0 else 0
    
    report = {
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "total_blocked": len(blocked),
        "total_replayed": total_replayed,
        "false_negatives": false_negatives,
        "profitable_count": profitable_count,
        "false_negative_rate_pct": round(false_negative_rate, 2),
        "missed_pnl_usd": round(total_missed_pnl, 2),
        "avg_pnl_per_trade": round(total_missed_pnl / total_replayed, 2) if total_replayed > 0 else 0,
        "replayed_trades": replayed
    }
    
    # Save report
    Path("logs").mkdir(exist_ok=True)
    with open("logs/missed_replay_report.json", "w") as f:
        json.dump(report, f, indent=2)
    
    # Print summary
    print(f"\n{'='*60}")
    print(f"📊 Missed Opportunity Replay Complete")
    print(f"{'='*60}")
    print(f"Total Blocked Signals: {len(blocked)}")
    print(f"Replayed (met relaxed criteria): {total_replayed}")
    print(f"False Negatives (profitable): {false_negatives} ({false_negative_rate:.1f}%)")
    print(f"Total Missed P&L: ${total_missed_pnl:.2f}")
    print(f"Avg P&L per Trade: ${report['avg_pnl_per_trade']:.2f}")
    print(f"\n📁 Report saved to: logs/missed_replay_report.json")
    
    return report


def get_latest_replay_report():
    """
    Load the most recent replay report.
    
    Returns:
        dict: Replay report data or empty dict if not found
    """
    report_path = Path("logs/missed_replay_report.json")
    
    if not report_path.exists():
        return {}
    
    try:
        with open(report_path, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️  Could not load replay report: {e}")
        return {}
