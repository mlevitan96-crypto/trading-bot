from flask import Flask, render_template, jsonify, request
import json
import os
import pandas as pd
from datetime import datetime
import sys
import pytz
import traceback
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from portfolio_tracker import get_portfolio_stats, get_hourly_pnl, get_recent_trades, get_portfolio_history, get_arizona_time, load_portfolio
from position_manager import get_open_futures_positions
from blofin_client import BlofinClient, get_current_price
from blofin_futures_client import BlofinFuturesClient
from signal_activity_logger import get_recent_signals, get_signal_summary
from daily_stats_tracker import get_daily_summary, check_and_reset_if_new_day
from futures_portfolio_tracker import get_futures_stats

ARIZONA_TZ = pytz.timezone('America/Phoenix')

template_folder = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'dashboard', 'templates')
static_folder = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'dashboard', 'static')
app = Flask(__name__, template_folder=template_folder, static_folder=static_folder)

blofin = BlofinClient()
blofin_futures = BlofinFuturesClient()


def read_json_log(filename):
    """Read JSON log file or return default."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    filepath = os.path.join(base_dir, "logs", filename)
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def get_risk_metrics():
    """Calculate comprehensive risk metrics."""
    performance_data = read_json_log("performance.json")
    if isinstance(performance_data, list):
        performance = performance_data[-1] if performance_data else {}
    else:
        performance = performance_data or {}
    
    risk_metrics_data = read_json_log("risk_metrics.json") or {}
    portfolio_stats = get_portfolio_stats()
    trades = get_recent_trades(limit=1000)
    
    metrics = {
        "sharpe": None,
        "sortino": None,
        "drawdown": performance.get("max_drawdown", performance.get("max_drawdown_pct", 0)),
        "win_rate": 0,
        "avg_roi": 0
    }
    
    # Get latest Sharpe and Sortino from risk_metrics.json
    if risk_metrics_data and "sharpe_history" in risk_metrics_data:
        sharpe_history = risk_metrics_data["sharpe_history"]
        if sharpe_history:
            metrics["sharpe"] = round(sharpe_history[-1]["sharpe"], 2)
    
    if risk_metrics_data and "sortino_history" in risk_metrics_data:
        sortino_history = risk_metrics_data["sortino_history"]
        if sortino_history:
            metrics["sortino"] = round(sortino_history[-1]["sortino"], 2)
    
    # Calculate win rate and avg ROI
    if trades:
        winning_trades = [t for t in trades if t.get("realized_pnl", 0) > 0]
        metrics["win_rate"] = round((len(winning_trades) / len(trades)) * 100, 1) if trades else 0
        
        total_roi = sum(t.get("roi_pct", 0) for t in trades)
        metrics["avg_roi"] = round(total_roi / len(trades), 2) if trades else 0
    
    return metrics


def get_missed_stats():
    """Get statistics about missed/blocked signals."""
    missed_data = read_json_log("missed_opportunities.json") or {}
    
    if isinstance(missed_data, dict) and "missed_trades" in missed_data:
        missed_trades = missed_data["missed_trades"]
    else:
        missed_trades = []
    
    # Count by filter reason
    by_filter = {}
    for trade in missed_trades:
        reason = trade.get("filter_reason", "unknown")
        if reason not in by_filter:
            by_filter[reason] = {"count": 0, "total_roi": 0}
        by_filter[reason]["count"] += 1
        by_filter[reason]["total_roi"] += trade.get("predicted_roi", 0)
    
    return {
        "total_missed": len(missed_trades),
        "by_filter": by_filter,
        "recent": missed_trades[-10:][::-1]
    }


def get_regime_history():
    """Get regime change history."""
    regime_weights = read_json_log("regime_weights.json")
    if isinstance(regime_weights, list):
        return regime_weights[-20:] if regime_weights else []
    elif isinstance(regime_weights, dict) and "history" in regime_weights:
        history = regime_weights["history"]
        return history[-20:] if history else []
    else:
        return []


def format_phoenix_time(iso_timestamp):
    """Convert ISO timestamp to Phoenix timezone formatted string."""
    if not iso_timestamp:
        return "N/A"
    try:
        dt = datetime.fromisoformat(iso_timestamp)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=pytz.UTC)
        phoenix_dt = dt.astimezone(ARIZONA_TZ)
        return phoenix_dt.strftime("%m/%d %H:%M:%S")
    except:
        return "N/A"


def get_closed_futures_positions(limit=100):
    """
    Load closed positions from SQLite (primary) with JSONL fallback.
    
    Phase 4 Tri-Layer Architecture: Reads from SQLite for analytics.
    Falls back to JSONL files if SQLite is unavailable.
    
    Returns list of closed positions formatted for dashboard display.
    """
    from src.data_registry import DataRegistry as DR
    
    try:
        # Limit to last 500 trades for performance (dashboard tables don't show all history)
        closed_positions = DR.get_closed_trades_from_db(limit=500, symbol=None)
        if closed_positions:
            print(f"📊 [DASHBOARD] Loaded {len(closed_positions)} closed trades from SQLite (limited to 500 for performance)")
        else:
            closed_positions = []
    except Exception as e:
        print(f"⚠️  [DASHBOARD] SQLite read failed, falling back to JSONL: {e}")
        data = read_json_log("positions_futures.json")
        if not data:
            return []
        closed_positions = data.get("closed_positions", [])
    if not closed_positions:
        return []
    
    formatted = []
    for pos in closed_positions:
        try:
            entry_time = pos.get("opened_at", pos.get("entry_time", ""))
            exit_time = pos.get("closed_at", pos.get("exit_time", ""))
            entry_price = pos.get("entry_price", 0)
            exit_price = pos.get("exit_price", 0)
            size = pos.get("size", pos.get("notional_size", 0))
            direction = pos.get("direction", "LONG")
            
            gross_pnl = pos.get("gross_pnl", 0)
            net_pnl = pos.get("net_pnl", pos.get("realized_pnl", 0))
            fees = pos.get("trading_fees", pos.get("fees", 0)) + pos.get("funding_fees", 0)
            roi_pct = pos.get("final_roi", pos.get("roi_pct", 0))
            
            if isinstance(roi_pct, float) and abs(roi_pct) < 1:
                roi_pct = roi_pct * 100
            
            hold_duration_s = 0
            try:
                if entry_time and exit_time:
                    entry_dt = datetime.fromisoformat(entry_time.replace("Z", "+00:00"))
                    exit_dt = datetime.fromisoformat(exit_time.replace("Z", "+00:00"))
                    hold_duration_s = (exit_dt - entry_dt).total_seconds()
            except:
                pass
            
            formatted.append({
                "symbol": pos.get("symbol", "UNKNOWN"),
                "strategy": pos.get("strategy", "unknown"),
                "direction": direction,
                "entry_time": entry_time,
                "exit_time": exit_time,
                "entry_time_formatted": format_phoenix_time(entry_time),
                "exit_time_formatted": format_phoenix_time(exit_time),
                "size": size,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "hold_duration_s": hold_duration_s,
                "gross_pnl": gross_pnl,
                "fees": fees,
                "net_pnl": net_pnl,
                "roi_pct": roi_pct,
                "conviction": pos.get("conviction", "UNKNOWN"),
                "venue": "futures"
            })
        except Exception as e:
            continue
    
    def get_exit_ts(p):
        try:
            exit_time = p.get("exit_time", "")
            if not exit_time:
                return 0
            dt = datetime.fromisoformat(exit_time.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=pytz.UTC)
            return dt.timestamp()
        except:
            return 0
    
    formatted.sort(key=get_exit_ts, reverse=True)
    
    return formatted[:limit]


def get_all_closed_positions_stats():
    """Get summary statistics for ALL closed futures positions from SQLite."""
    from src.data_registry import DataRegistry as DR
    
    try:
        # PERFORMANCE: Limit to last 5000 trades for stats (enough for accurate totals without loading everything)
        closed_positions = DR.get_closed_trades_from_db(limit=5000, symbol=None)
    except Exception as e:
        print(f"⚠️  [DASHBOARD] SQLite stats read failed, falling back to JSONL: {e}")
        data = read_json_log("positions_futures.json")
        if not data:
            return {"total_positions": 0, "total_net_pnl": 0, "total_winners": 0, "total_losers": 0, "avg_hold_duration_s": 0, "avg_roi_pct": 0}
        closed_positions = data.get("closed_positions", [])
    
    if not closed_positions:
        return {"total_positions": 0, "total_net_pnl": 0, "total_winners": 0, "total_losers": 0, "avg_hold_duration_s": 0, "avg_roi_pct": 0}
    
    total_net_pnl = 0
    total_roi = 0
    winners = 0
    losers = 0
    
    for pos in closed_positions:
        net_pnl = pos.get("net_pnl", pos.get("realized_pnl", 0))
        roi = pos.get("final_roi", pos.get("roi_pct", 0))
        if isinstance(roi, float) and abs(roi) < 1:
            roi = roi * 100
        
        total_net_pnl += net_pnl
        total_roi += roi
        
        if net_pnl > 0:
            winners += 1
        else:
            losers += 1
    
    n = len(closed_positions)
    return {
        "total_positions": n,
        "total_net_pnl": round(total_net_pnl, 2),
        "total_winners": winners,
        "total_losers": losers,
        "win_rate": round((winners / n * 100), 1) if n > 0 else 0,
        "avg_roi_pct": round(total_roi / n, 2) if n > 0 else 0
    }


def build_closed_positions(trades):
    """
    Build closed positions from trades using FIFO matching per (symbol, strategy).
    
    Matches buy/sell pairs to create complete position records with entry/exit prices.
    """
    if not trades:
        return []
    
    # Sort trades chronologically (oldest first) for FIFO matching
    def get_timestamp(trade):
        try:
            return datetime.fromisoformat(trade.get("timestamp", ""))
        except:
            return datetime.min
    
    sorted_trades = sorted(trades, key=get_timestamp)
    
    # Maintain separate queues per (symbol, strategy_base)
    open_lots = {}
    closed_positions = []
    
    for trade in sorted_trades:
        symbol = trade.get("symbol", "UNKNOWN")
        side = trade.get("side", "")
        strategy = trade.get("strategy", "")
        
        # Strip "-Exit" suffix for strategy matching
        strategy_base = strategy.replace("-Exit", "").replace("-exit", "")
        
        # Queue key
        queue_key = f"{symbol}_{strategy_base}"
        
        if side == "buy":
            # Push lot to queue
            lot = {
                "entry_time": trade.get("timestamp", ""),
                "entry_price": trade.get("price", 0),
                "size": trade.get("position_size", 0),
                "entry_fees": trade.get("fees", 0)
            }
            
            if queue_key not in open_lots:
                open_lots[queue_key] = []
            open_lots[queue_key].append(lot)
        
        elif side == "sell":
            # Consume from queue FIFO
            if queue_key not in open_lots or not open_lots[queue_key]:
                continue
            
            exit_price = trade.get("price", 0)
            exit_time = trade.get("timestamp", "")
            exit_fees = trade.get("fees", 0)
            remaining_exit_size = trade.get("position_size", 0)
            
            # Match against open lots
            while remaining_exit_size > 0.01 and open_lots[queue_key]:
                lot = open_lots[queue_key][0]
                lot_size = lot["size"]
                
                # Determine matched size
                matched_size = min(lot_size, remaining_exit_size)
                
                # Calculate metrics
                entry_price = lot["entry_price"]
                gross_pnl = (exit_price - entry_price) / entry_price * matched_size
                
                # Pro-rate fees based on matched portion
                entry_fee_portion = (matched_size / lot_size) if lot_size > 0 else 0
                exit_fee_portion = (matched_size / trade.get("position_size", 1)) if trade.get("position_size", 1) > 0 else 0
                
                entry_fees_allocated = lot["entry_fees"] * entry_fee_portion
                exit_fees_allocated = exit_fees * exit_fee_portion
                total_fees = entry_fees_allocated + exit_fees_allocated
                
                net_pnl = gross_pnl - total_fees
                roi_pct = ((exit_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
                
                # Calculate hold duration
                try:
                    entry_dt = datetime.fromisoformat(lot["entry_time"])
                    exit_dt = datetime.fromisoformat(exit_time)
                    hold_duration_s = (exit_dt - entry_dt).total_seconds()
                except:
                    hold_duration_s = 0
                
                # Create closed position record
                closed_positions.append({
                    "symbol": symbol,
                    "strategy": strategy_base,
                    "entry_time": lot["entry_time"],
                    "exit_time": exit_time,
                    "entry_time_formatted": format_phoenix_time(lot["entry_time"]),
                    "exit_time_formatted": format_phoenix_time(exit_time),
                    "size": matched_size,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "hold_duration_s": hold_duration_s,
                    "gross_pnl": gross_pnl,
                    "fees": total_fees,
                    "net_pnl": net_pnl,
                    "roi_pct": roi_pct
                })
                
                # Update lot size and remaining fees, or remove if fully closed
                lot["size"] -= matched_size
                lot["entry_fees"] -= entry_fees_allocated
                remaining_exit_size -= matched_size
                
                if lot["size"] < 0.01:
                    open_lots[queue_key].pop(0)
    
    return closed_positions


def get_position_history_summary(closed_positions):
    """Generate summary statistics for position history."""
    if not closed_positions:
        return {
            "total_positions": 0,
            "total_net_pnl": 0,
            "total_winners": 0,
            "total_losers": 0,
            "avg_hold_duration_s": 0,
            "avg_roi_pct": 0
        }
    
    winners = [p for p in closed_positions if p["net_pnl"] > 0]
    losers = [p for p in closed_positions if p["net_pnl"] <= 0]
    total_net_pnl = sum(p["net_pnl"] for p in closed_positions)
    avg_hold = sum(p["hold_duration_s"] for p in closed_positions) / len(closed_positions)
    avg_roi = sum(p["roi_pct"] for p in closed_positions) / len(closed_positions)
    
    return {
        "total_positions": len(closed_positions),
        "total_net_pnl": round(total_net_pnl, 2),
        "total_winners": len(winners),
        "total_losers": len(losers),
        "avg_hold_duration_s": int(avg_hold),
        "avg_roi_pct": round(avg_roi, 2)
    }


@app.route("/shadow")
def shadow_research_dashboard():
    """Shadow Research dashboard for new experimental symbols."""
    try:
        from src.shadow_research import get_shadow_engine
        import time
        engine = get_shadow_engine()
        status = engine.get_status()
        
        vol_research = status.get("vol_research", {})
        ensemble_tel = status.get("ensemble_telemetry", {})
        promo_status = status.get("promotion_status", {})
        total_trades = status.get("total_shadow_trades", 0)
        symbols = status.get("symbols", [])
        
        symbol_rows = ""
        for symbol in sorted(symbols):
            vol = vol_research.get(symbol, {})
            ens = ensemble_tel.get(symbol, {})
            promo = promo_status.get(symbol, {})
            
            is_promoted = promo.get("promoted", False)
            promo_class = "positive" if is_promoted else "neutral"
            promo_text = "LIVE" if is_promoted else "SHADOW"
            
            hours_obs = (time.time() - promo.get("start_ts", time.time())) / 3600
            trades_logged = promo.get("trades_logged", 0)
            failure_reasons = promo.get("failure_reasons", [])
            
            vol_annual = vol.get("realized_vol_annual_pct", 0)
            vol_spike = vol.get("vol_spike_score", 0)
            avg_spread = vol.get("avg_spread_bps", 0)
            
            ens_p50 = ens.get("p50", 0)
            ens_p75 = ens.get("p75", 0)
            trades_count = ens.get("trades", 0)
            wins_count = ens.get("wins", 0)
            win_rate = (wins_count / trades_count * 100) if trades_count > 0 else 0
            
            reasons_text = ", ".join(failure_reasons[:3]) if failure_reasons else "N/A"
            if len(failure_reasons) > 3:
                reasons_text += f" (+{len(failure_reasons)-3} more)"
            
            symbol_rows += f"""
            <tr>
                <td><strong>{symbol}</strong></td>
                <td class="{promo_class}">{promo_text}</td>
                <td>{vol_annual:.1f}%</td>
                <td>{vol_spike:.3f}</td>
                <td>{avg_spread:.2f}</td>
                <td>{ens_p50:.3f} / {ens_p75:.3f}</td>
                <td>{trades_count}</td>
                <td>{win_rate:.1f}%</td>
                <td>{hours_obs:.1f}h</td>
                <td style="font-size:0.85em;">{reasons_text}</td>
            </tr>
            """
        
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Shadow Research Dashboard</title>
    <meta http-equiv="refresh" content="30">
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #0a0e27; color: #e0e6ed; padding: 20px; margin: 0; }}
        .container {{ max-width: 1600px; margin: 0 auto; }}
        h1 {{ color: #00d4ff; margin-bottom: 10px; font-size: 2.5em; display: flex; align-items: center; gap: 15px; }}
        .header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px; }}
        .back-link {{ background: #1e2749; padding: 10px 20px; border-radius: 5px; text-decoration: none; color: #00d4ff; }}
        .back-link:hover {{ background: #2a3558; }}
        .stat-card {{ display: inline-block; background: #1e2749; padding: 15px 25px; margin: 10px 10px 10px 0; border-radius: 8px; min-width: 180px; }}
        .stat-label {{ color: #8b95a5; font-size: 0.9em; margin-bottom: 5px; }}
        .stat-value {{ color: #00d4ff; font-size: 1.8em; font-weight: bold; }}
        table {{ border-collapse: collapse; width: 100%; margin-top: 20px; background: #161b33; border-radius: 8px; overflow: hidden; }}
        th, td {{ border: 1px solid #2a3558; padding: 12px; text-align: left; }}
        th {{ background: #1e2749; color: #00d4ff; font-weight: 600; }}
        tr:hover {{ background: #1a1f3a; }}
        .positive {{ color: #00ff88; font-weight: bold; }}
        .negative {{ color: #ff4466; font-weight: bold; }}
        .neutral {{ color: #ffa500; font-weight: bold; }}
        .section {{ background: #0f1428; padding: 25px; border-radius: 10px; margin-bottom: 30px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }}
        h2 {{ color: #00d4ff; margin-top: 0; padding-bottom: 10px; border-bottom: 2px solid #00d4ff; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🔬 Shadow Research Dashboard</h1>
            <a href="/" class="back-link">← Back to Main Dashboard</a>
        </div>
        
        <div class="section">
            <div class="stat-card">
                <div class="stat-label">Total Symbols</div>
                <div class="stat-value">{len(symbols)}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Shadow Trades</div>
                <div class="stat-value">{total_trades}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Promoted Symbols</div>
                <div class="stat-value">{sum(1 for p in promo_status.values() if p.get('promoted', False))}</div>
            </div>
        </div>
        
        <div class="section">
            <h2>📊 Symbol Research Status</h2>
            <table>
                <thead>
                    <tr>
                        <th>Symbol</th>
                        <th>Status</th>
                        <th>Vol (Annual)</th>
                        <th>Vol Spike Score</th>
                        <th>Avg Spread (bps)</th>
                        <th>Ensemble P50/P75</th>
                        <th>Trades</th>
                        <th>Win Rate</th>
                        <th>Observed</th>
                        <th>Block Reasons</th>
                    </tr>
                </thead>
                <tbody>
                    {symbol_rows}
                </tbody>
            </table>
        </div>
        
        <div class="section">
            <p style="color: #8b95a5; font-size: 0.9em;">
                <strong>Note:</strong> Shadow symbols collect real telemetry with zero live capital until strict promotion criteria are met.
                Criteria include: 40+ trades, 24+ hours observed, positive P&L expectancy, win rate >50%, and ensemble confidence >0.60.
            </p>
        </div>
    </div>
</body>
</html>
        """
        
        return html
        
    except Exception as e:
        return f"<pre>Shadow Research Dashboard Error: {str(e)}</pre>"


@app.route("/health")
def health():
    """Lightweight health check endpoint for deployments."""
    return jsonify({"status": "healthy", "service": "crypto-trading-bot"}), 200


@app.route("/trader")
def index():
    """Redirect to Phase 8 Trader Dashboard (moved from root to /trader)."""
    from flask import redirect
    return redirect("/phase8")


@app.route("/legacy")
def legacy_dashboard():
    """Legacy main dashboard page with all data."""
    portfolio = load_portfolio()
    portfolio_stats = get_portfolio_stats()
    portfolio_history = get_portfolio_history(limit=200)
    open_positions = []  # Spot trading disabled - futures-only architecture
    open_futures_positions = get_open_futures_positions()
    risk_metrics = get_risk_metrics()
    missed_stats = get_missed_stats()
    regime_history = get_regime_history()
    
    # Load closed positions directly from positions_futures.json (authoritative source)
    closed_positions_recent = get_closed_futures_positions(limit=100)
    position_summary = get_all_closed_positions_stats()
    
    # Calculate full trade metrics from positions_futures.json
    total_trades_count = position_summary.get("total_positions", 0)
    full_win_rate = position_summary.get("win_rate", 0)
    
    # Enhance open spot positions with current prices and ROI
    for pos in open_positions:
        try:
            current_price = get_current_price(pos["symbol"])
            pos["current_price"] = current_price
            pos["roi"] = round(((current_price - pos["entry_price"]) / pos["entry_price"]) * 100, 2)
            pos["venue"] = "spot"
        except:
            pos["current_price"] = pos.get("peak_price", pos["entry_price"])
            pos["roi"] = 0
            pos["venue"] = "spot"
    
    # Enhance open futures positions with current prices and leveraged ROI
    for pos in open_futures_positions:
        try:
            # Use Blofin futures client to get mark price
            current_price = blofin_futures.get_mark_price(pos["symbol"])
            pos["current_price"] = current_price
            
            # Calculate price ROI
            if pos["direction"] == "LONG":
                price_roi = ((current_price - pos["entry_price"]) / pos["entry_price"])
            else:  # SHORT
                price_roi = ((pos["entry_price"] - current_price) / pos["entry_price"])
            
            # Apply leverage
            leveraged_roi = price_roi * pos["leverage"]
            pos["roi"] = round(leveraged_roi * 100, 2)
            pos["venue"] = "futures"
        except:
            pos["current_price"] = pos.get("peak_price" if pos.get("direction") == "LONG" else "trough_price", pos["entry_price"])
            pos["roi"] = 0
            pos["venue"] = "futures"
    
    # Portfolio snapshots for chart
    snapshots = []
    for entry in portfolio_history:
        snapshots.append({
            "timestamp": entry.get("timestamp", ""),
            "value": entry.get("portfolio_value", entry.get("value", 0))
        })
    
    # Position exposure for pie chart (combining spot and futures)
    position_exposure = {}
    for pos in open_positions:
        position_exposure[pos["symbol"]] = position_exposure.get(pos["symbol"], 0) + pos["size"]
    for pos in open_futures_positions:
        # For futures, use margin collateral as size for exposure calculation
        margin = pos.get("margin_collateral", pos["size"] / pos.get("leverage", 1))
        position_exposure[pos["symbol"]] = position_exposure.get(pos["symbol"], 0) + margin
    
    # Get daily stats and futures stats for combined metrics
    daily_stats = get_daily_summary()
    futures_stats = get_futures_stats()
    
    # Calculate combined total metrics (all-time)
    combined_total_trades = total_trades_count + futures_stats["total_trades"]
    combined_total_wins = position_summary["total_winners"] + futures_stats["winning_trades"]
    combined_total_losses = position_summary["total_losers"] + (futures_stats["total_trades"] - futures_stats["winning_trades"])
    combined_total_pnl = portfolio_stats["total_profit"] + futures_stats["total_pnl"]
    combined_win_rate = round((combined_total_wins / combined_total_trades * 100), 1) if combined_total_trades > 0 else 0
    
    context = {
        "portfolio": {
            "value": portfolio_stats["current_value"],
            "starting_capital": portfolio_stats["starting_capital"],
            "total_profit": portfolio_stats["total_profit"],
            "snapshots": snapshots,
            "trades": get_recent_trades(limit=100),
            "positions": position_exposure
        },
        "open_positions": open_positions,
        "open_futures_positions": open_futures_positions,
        "total_open_positions": len(open_positions) + len(open_futures_positions),
        "risk_metrics": risk_metrics,
        "missed_stats": missed_stats,
        "regime_history": regime_history,
        "closed_positions": closed_positions_recent,
        "position_summary": position_summary,
        "total_trades_count": total_trades_count,
        "full_win_rate": full_win_rate,
        "daily_stats": daily_stats,
        "futures_stats": futures_stats,
        "combined_totals": {
            "trades": combined_total_trades,
            "wins": combined_total_wins,
            "losses": combined_total_losses,
            "pnl": combined_total_pnl,
            "win_rate": combined_win_rate
        },
        "last_update": get_arizona_time().strftime("%Y-%m-%d %H:%M:%S %Z")
    }
    
    return render_template("dashboard.html", **context)


@app.route("/api/environment")
def api_environment():
    """API endpoint to check if running on Reserved VM or Development."""
    is_reserved_vm = os.environ.get("REPLIT_DEPLOYMENT") == "1"
    return jsonify({
        "environment": "reserved_vm" if is_reserved_vm else "development",
        "is_reserved_vm": is_reserved_vm
    })


@app.route("/api/refresh")
def api_refresh():
    """API endpoint for dashboard refresh."""
    portfolio = load_portfolio()
    portfolio_stats = get_portfolio_stats()
    open_positions = []  # Spot trading disabled - futures-only architecture
    open_futures_positions = get_open_futures_positions()
    risk_metrics = get_risk_metrics()
    missed_stats = get_missed_stats()
    
    # Get signal activity
    recent_signals = get_recent_signals(limit=20)
    signal_summary = get_signal_summary()
    
    # Load closed positions directly from positions_futures.json (authoritative source)
    closed_positions_recent = get_closed_futures_positions(limit=100)
    position_summary = get_all_closed_positions_stats()
    
    # Calculate full trade metrics from positions_futures.json
    total_trades_count = position_summary.get("total_positions", 0)
    full_win_rate = position_summary.get("win_rate", 0)
    
    # Enhance spot positions with current data
    for pos in open_positions:
        try:
            current_price = get_current_price(pos["symbol"])
            pos["current_price"] = current_price
            pos["roi"] = round(((current_price - pos["entry_price"]) / pos["entry_price"]) * 100, 2)
            pos["venue"] = "spot"
        except:
            pos["current_price"] = pos.get("peak_price", pos["entry_price"])
            pos["roi"] = 0
            pos["venue"] = "spot"
    
    # Enhance futures positions with current data
    for pos in open_futures_positions:
        try:
            # Use Blofin futures client to get mark price
            current_price = blofin_futures.get_mark_price(pos["symbol"])
            pos["current_price"] = current_price
            
            # Calculate price ROI
            if pos["direction"] == "LONG":
                price_roi = ((current_price - pos["entry_price"]) / pos["entry_price"])
            else:  # SHORT
                price_roi = ((pos["entry_price"] - current_price) / pos["entry_price"])
            
            # Apply leverage
            leveraged_roi = price_roi * pos["leverage"]
            pos["roi"] = round(leveraged_roi * 100, 2)
            pos["venue"] = "futures"
        except:
            pos["current_price"] = pos.get("peak_price" if pos.get("direction") == "LONG" else "trough_price", pos["entry_price"])
            pos["roi"] = 0
            pos["venue"] = "futures"
    
    # Get daily stats and futures stats for combined metrics
    daily_stats = get_daily_summary()
    futures_stats = get_futures_stats()
    
    # Calculate combined total metrics (all-time)
    combined_total_trades = total_trades_count + futures_stats["total_trades"]
    combined_total_wins = position_summary["total_winners"] + futures_stats["winning_trades"]
    combined_total_losses = position_summary["total_losers"] + (futures_stats["total_trades"] - futures_stats["winning_trades"])
    combined_total_pnl = portfolio_stats["total_profit"] + futures_stats["total_pnl"]
    combined_win_rate = round((combined_total_wins / combined_total_trades * 100), 1) if combined_total_trades > 0 else 0
    
    return jsonify({
        "portfolio_value": portfolio_stats["current_value"],
        "open_positions": open_positions,
        "open_futures_positions": open_futures_positions,
        "total_open_positions": len(open_positions) + len(open_futures_positions),
        "closed_positions": closed_positions_recent,
        "position_summary": position_summary,
        "risk_metrics": risk_metrics,
        "missed_stats": missed_stats,
        "signal_activity": recent_signals,
        "signal_summary": signal_summary,
        "total_trades_count": total_trades_count,
        "full_win_rate": full_win_rate,
        "daily_stats": daily_stats,
        "futures_stats": futures_stats,
        "combined_totals": {
            "trades": combined_total_trades,
            "wins": combined_total_wins,
            "losses": combined_total_losses,
            "pnl": combined_total_pnl,
            "win_rate": combined_win_rate
        },
        "last_update": get_arizona_time().strftime("%Y-%m-%d %H:%M:%S %Z")
    })


@app.route("/elite")
def elite_dashboard():
    """Elite System diagnostics dashboard."""
    from pathlib import Path
    
    def load_elite_json(filename, fallback=None):
        try:
            filepath = Path("logs") / filename if "logs" in str(Path(filename).parent) else Path("configs") / filename
            if not filepath.exists():
                filepath = Path(filename)
            with open(filepath) as f:
                return json.load(f)
        except:
            return fallback or {}
    
    thresholds = load_elite_json("configs/thresholds.json")
    attribution = load_elite_json("logs/attribution_summary.json")
    decay = load_elite_json("logs/signal_decay.json")
    audit = load_elite_json("logs/protective_mode_audit.json")
    health = load_elite_json("logs/execution_health.json")
    budgets = load_elite_json("configs/risk_budgets.json")
    shadow = load_elite_json("logs/shadow_mode_results.json")
    
    html = """
<!DOCTYPE html>
<html>
<head>
    <title>Elite Bot Diagnostics</title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #0a0e27; color: #e0e6ed; padding: 20px; margin: 0; }
        .container { max-width: 1400px; margin: 0 auto; }
        h1 { color: #00d4ff; margin-bottom: 10px; font-size: 2.5em; }
        h2 { color: #00d4ff; margin-top: 40px; margin-bottom: 15px; border-bottom: 2px solid #00d4ff; padding-bottom: 10px; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px; }
        .back-link { background: #1e2749; padding: 10px 20px; border-radius: 5px; text-decoration: none; color: #00d4ff; }
        .back-link:hover { background: #2a3558; }
        table { border-collapse: collapse; width: 100%; margin-bottom: 30px; background: #161b33; border-radius: 8px; overflow: hidden; }
        th, td { border: 1px solid #2a3558; padding: 12px; text-align: left; }
        th { background: #1e2749; color: #00d4ff; font-weight: 600; }
        tr:hover { background: #1a1f3a; }
        .section { margin-bottom: 50px; background: #0f1428; padding: 25px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
        .stat-card { display: inline-block; background: #1e2749; padding: 15px 25px; margin: 10px 10px 10px 0; border-radius: 8px; min-width: 200px; }
        .stat-label { color: #8b95a5; font-size: 0.9em; margin-bottom: 5px; }
        .stat-value { color: #00d4ff; font-size: 1.8em; font-weight: bold; }
        .positive { color: #00ff88; }
        .negative { color: #ff4466; }
        .neutral { color: #ffa500; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🧠 Elite Bot Diagnostics</h1>
            <a href="/" class="back-link">← Back to Main Dashboard</a>
        </div>
""" + f"""
        <div class="section">
            <h2>📊 Adaptive Thresholds by Regime</h2>
            <table>
                <tr><th>Regime</th><th>ROI Threshold</th><th>Ensemble Threshold</th></tr>
                {''.join(f'<tr><td>{r}</td><td>{v.get("roi", 0):.4f} ({v.get("roi", 0)*100:.2f}%)</td><td>{v.get("ensemble", 0):.2f}</td></tr>' for r, v in thresholds.items())}
            </table>
        </div>

        <div class="section">
            <h2>📈 Strategy-Regime Attribution</h2>
            <table>
                <tr><th>Symbol</th><th>Strategy</th><th>Regime</th><th>Trades</th><th>Win Rate</th><th>Avg ROI</th><th>Gross P&L</th><th>Net P&L</th></tr>
                {''.join(f'<tr><td>{x["symbol"]}</td><td>{x["strategy"]}</td><td>{x["regime"]}</td><td>{x["trades"]}</td><td class="{"positive" if x["winrate"] >= 0.5 else "negative"}">{x["winrate"]*100:.1f}%</td><td class="{"positive" if x["avg_roi"] > 0 else "negative"}">{x["avg_roi"]*100:.2f}%</td><td class="{"positive" if x["gross_pnl"] > 0 else "negative"}">{x["gross_pnl"]:.4f}</td><td class="{"positive" if x["net_pnl"] > 0 else "negative"}">{x["net_pnl"]:.4f}</td></tr>' for x in attribution.get("summary", []))}
            </table>
        </div>

        <div class="section">
            <h2>📉 Signal Decay Tracker</h2>
            <table>
                <tr><th>Symbol | Strategy</th><th>Initial Strength</th><th>Latest Strength</th><th>Mean</th><th>Std Dev</th><th>Decay</th></tr>
                {''.join(f'<tr><td>{k}</td><td>{v["initial"]:.3f}</td><td>{v["latest"]:.3f}</td><td>{v["mean"]:.3f}</td><td>{v["std"]:.3f}</td><td class="{"negative" if v["decay"] < 0 else "positive"}">{v["decay"]:.4f}</td></tr>' for k, v in decay.get("tracks", {}).items())}
            </table>
        </div>

        <div class="section">
            <h2>🛡️ Protective Mode Audit</h2>
            <div class="stat-card">
                <div class="stat-label">Total Blocks</div>
                <div class="stat-value">{audit.get("total_blocks", 0)}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Missed P&L (Estimate)</div>
                <div class="stat-value positive">{audit.get("missed_pnl_estimate", 0):.4f}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Avoided Drawdown</div>
                <div class="stat-value negative">{audit.get("avoided_drawdown_estimate", 0):.4f}</div>
            </div>
            <table>
                <tr><th>Blocking Reason</th><th>Count</th></tr>
                {''.join(f'<tr><td>{k}</td><td>{v}</td></tr>' for k, v in audit.get("blocked_reasons", {}).items())}
            </table>
        </div>

        <div class="section">
            <h2>⚙️ Execution Health Monitor</h2>
            <div class="stat-card">
                <div class="stat-label">Average Slippage</div>
                <div class="stat-value {'positive' if health.get('avg_slippage', 0) < 0.005 else 'negative'}">{health.get("avg_slippage", 0)*100:.3f}%</div>
            </div>
            <table>
                <tr><th>Issue Type</th><th>Count</th></tr>
                {''.join(f'<tr><td>{k}</td><td>{v}</td></tr>' for k, v in health.get("issue_counts", {}).items())}
            </table>
        </div>

        <div class="section">
            <h2>💰 Risk Budget Allocator</h2>
            <table>
                <tr><th>Symbol | Strategy</th><th>Allocated Budget ($)</th></tr>
                {''.join(f'<tr><td>{k}</td><td>${v:.2f}</td></tr>' for k, v in budgets.get("budgets", {}).items())}
            </table>
        </div>

        <div class="section">
            <h2>🧪 Shadow Mode Experiments</h2>
            <table>
                <tr><th>Experiment Name</th><th>Config</th><th>Win Rate</th><th>Avg ROI</th><th>Drawdown</th></tr>
                {''.join(f'<tr><td>{e["name"]}</td><td>{json.dumps(e["config"])}</td><td class="{"positive" if e["metrics"]["winrate"] > 0.5 else "negative"}">{e["metrics"]["winrate"]*100:.1f}%</td><td class="{"positive" if e["metrics"]["avg_roi"] > 0 else "negative"}">{e["metrics"]["avg_roi"]*100:.2f}%</td><td class="negative">{e["metrics"]["drawdown"]*100:.2f}%</td></tr>' for e in shadow.get("experiments", []))}
            </table>
        </div>

    </div>
</body>
</html>
    """
    return html


# ---------------------------
# Live Deployment Functions
# ---------------------------
def load_json_file(path, fallback=None):
    """Load JSON file with fallback."""
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return fallback or {}

def save_json_file(path, data):
    """Save JSON file with directory creation."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def backup_current_config():
    """Backup current live configs."""
    base_dir = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    deployed_path = base_dir / "configs" / "live_configs.json"
    backup_dir = base_dir / "configs" / "backups"
    
    current = load_json_file(deployed_path, {})
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    save_json_file(backup_dir / f"live_configs_backup_{ts}.json", current)
    return ts

def deploy_promoted_experiments():
    """Deploy promoted experiments to production."""
    base_dir = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    promoted_path = base_dir / "logs" / "monthly_promoted_experiments.json"
    deployed_path = base_dir / "configs" / "live_configs.json"
    
    promoted_data = load_json_file(promoted_path, {})
    promoted = promoted_data.get("promoted", [])
    
    if not promoted:
        return {"success": False, "message": "No promoted experiments found"}
    
    ts = backup_current_config()
    deployed = load_json_file(deployed_path, {})
    
    for exp in promoted:
        name = exp["name"]
        config = exp["config"]
        deployed[name] = {
            "config": config,
            "source": "shadow_runner",
            "promoted_at": datetime.utcnow().isoformat(),
            "backup_id": ts,
            "metrics": exp.get("metrics", {})
        }
    
    save_json_file(deployed_path, deployed)
    return {"success": True, "count": len(promoted), "backup_id": ts}

def rollback_latest_config():
    """Rollback to latest backup."""
    base_dir = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    backup_dir = base_dir / "configs" / "backups"
    deployed_path = base_dir / "configs" / "live_configs.json"
    
    if not backup_dir.exists():
        return {"success": False, "message": "No backup directory found"}
    
    backups = sorted(backup_dir.glob("live_configs_backup_*.json"), reverse=True)
    if not backups:
        return {"success": False, "message": "No backups found"}
    
    latest = backups[0]
    data = load_json_file(latest, {})
    save_json_file(deployed_path, data)
    return {"success": True, "backup_file": latest.name}


@app.route("/deployments")
def deployments_dashboard():
    """Live deployment dashboard."""
    base_dir = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    deployed_path = base_dir / "configs" / "live_configs.json"
    promoted_path = base_dir / "logs" / "monthly_promoted_experiments.json"
    backup_dir = base_dir / "configs" / "backups"
    
    deployed = load_json_file(deployed_path, {})
    promoted_data = load_json_file(promoted_path, {})
    promoted = promoted_data.get("promoted", [])
    
    backups = []
    if backup_dir.exists():
        backups = sorted(backup_dir.glob("live_configs_backup_*.json"), reverse=True)
    
    html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Live Deployment Dashboard</title>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #0a0e27; color: #e0e6ed; padding: 20px; margin: 0; }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        h1 {{ color: #00d4ff; margin-bottom: 10px; font-size: 2.5em; }}
        h2 {{ color: #00d4ff; margin-top: 40px; margin-bottom: 15px; border-bottom: 2px solid #00d4ff; padding-bottom: 10px; }}
        .header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px; }}
        .back-link {{ background: #1e2749; padding: 10px 20px; border-radius: 5px; text-decoration: none; color: #00d4ff; }}
        .back-link:hover {{ background: #2a3558; }}
        table {{ border-collapse: collapse; width: 100%; margin-bottom: 30px; background: #161b33; border-radius: 8px; overflow: hidden; }}
        th, td {{ border: 1px solid #2a3558; padding: 12px; text-align: left; }}
        th {{ background: #1e2749; color: #00d4ff; font-weight: 600; }}
        tr:hover {{ background: #1a1f3a; }}
        .section {{ margin-bottom: 50px; background: #0f1428; padding: 25px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }}
        .positive {{ color: #00ff88; }}
        .negative {{ color: #ff4466; }}
        .neutral {{ color: #ffa500; }}
        .stat-card {{ display: inline-block; background: #1e2749; padding: 15px 25px; margin: 10px 10px 10px 0; border-radius: 8px; min-width: 200px; }}
        .stat-label {{ color: #8b95a5; font-size: 0.9em; margin-bottom: 5px; }}
        .stat-value {{ color: #00d4ff; font-size: 1.8em; font-weight: bold; }}
        .message {{ padding: 15px; margin-bottom: 20px; border-radius: 5px; }}
        .message.info {{ background: #00d4ff33; border-left: 4px solid #00d4ff; }}
        code {{ background: #1e2749; padding: 2px 6px; border-radius: 3px; }}
        pre {{ background: #161b33; padding: 15px; border-radius: 5px; overflow-x: auto; }}
        ol, ul {{ line-height: 1.8; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🚀 Live Deployment Dashboard</h1>
            <a href="/" class="back-link">⬅️ Main Dashboard</a>
        </div>

        <div class="section">
            <div class="stat-card">
                <div class="stat-label">Promoted Experiments</div>
                <div class="stat-value">{len(promoted)}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Live Configs</div>
                <div class="stat-value">{len(deployed)}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Backups Available</div>
                <div class="stat-value">{len(backups)}</div>
            </div>
        </div>

        <div class="section">
            <h2>🎯 Promoted Experiments (Ready for Deployment)</h2>
            {"<p class='neutral'>No promoted experiments found. Run monthly maintenance on 1st of month.</p>" if not promoted else ""}
            <table>
                <tr>
                    <th>Experiment Name</th>
                    <th>Configuration</th>
                    <th>Win Rate</th>
                    <th>Avg ROI</th>
                    <th>Max Drawdown</th>
                    <th>Status</th>
                </tr>
    """
    
    # Add each promoted experiment row
    for e in promoted:
        wr_class = 'positive' if e['metrics']['winrate'] >= 0.52 else 'negative'
        roi_class = 'positive' if e['metrics']['avg_roi'] > 0 else 'negative'
        dd_class = 'positive' if e['metrics']['drawdown'] <= 0.05 else 'negative'
        html += f"""
                <tr>
                    <td><strong>{e['name']}</strong></td>
                    <td><code>{json.dumps(e['config'], indent=2)}</code></td>
                    <td class="{wr_class}">{e['metrics']['winrate'] * 100:.1f}%</td>
                    <td class="{roi_class}">{e['metrics']['avg_roi'] * 100:.2f}%</td>
                    <td class="{dd_class}">{e['metrics']['drawdown'] * 100:.2f}%</td>
                    <td class="neutral">Pending Manual Deployment</td>
                </tr>
        """
    
    # Add deployment instructions if experiments exist
    deployment_msg = ""
    if promoted:
        deployment_msg = """
            <div class="message info">
                💡 <strong>Manual Deployment Required:</strong> Review experiments above, then run: <code>python3 deploy_configs.py</code>
            </div>
        """
    
    html += f"""
            </table>
            {deployment_msg}
        </div>

        <div class="section">
            <h2>📋 Currently Deployed Configs</h2>
            {"<p class='neutral'>No configs deployed yet.</p>" if not deployed else ""}
            <table>
                <tr>
                    <th>Config Name</th>
                    <th>Configuration</th>
                    <th>Deployed At</th>
                    <th>Backup ID</th>
                    <th>Win Rate</th>
                    <th>Avg ROI</th>
                </tr>
    """
    
    # Add each deployed config row
    for k, v in deployed.items():
        wr_val = v.get('metrics', {}).get('winrate', 0)
        roi_val = v.get('metrics', {}).get('avg_roi', 0)
        wr_class = 'positive' if wr_val >= 0.52 else 'neutral'
        roi_class = 'positive' if roi_val > 0 else 'neutral'
        promoted_at = v.get('promoted_at', 'N/A')[:19] if v.get('promoted_at') else 'N/A'
        html += f"""
                <tr>
                    <td><strong>{k}</strong></td>
                    <td><code>{json.dumps(v['config'], indent=2)}</code></td>
                    <td>{promoted_at}</td>
                    <td><code>{v.get('backup_id', 'N/A')}</code></td>
                    <td class="{wr_class}">{wr_val * 100:.1f}%</td>
                    <td class="{roi_class}">{roi_val * 100:.2f}%</td>
                </tr>
        """
    
    html += """
            </table>
        </div>

        <div class="section">
            <h2>🗂️ Configuration Backups</h2>
            {"<p class='neutral'>No backups found.</p>" if not backups else ""}
            <table>
                <tr>
                    <th>Backup File</th>
                    <th>Timestamp</th>
                    <th>Age</th>
                </tr>
    """
    
    # Add backup rows
    for b in backups[:10]:
        ts = b.name.replace('live_configs_backup_','').replace('.json','')
        age = (datetime.utcnow() - datetime.fromtimestamp(b.stat().st_mtime)).days
        html += f"""
                <tr>
                    <td><code>{b.name}</code></td>
                    <td>{ts}</td>
                    <td>{age} days ago</td>
                </tr>
        """
    
    rollback_msg = ""
    if backups:
        rollback_msg = """
            <div class="message info">
                💾 <strong>Rollback Available:</strong> To revert to latest backup, run: <code>python3 deploy_configs.py --rollback</code>
            </div>
        """
    
    html += f"""
            </table>
            {rollback_msg}
        </div>

        <div class="section">
            <h2>📖 Deployment Guide</h2>
            <h3>Automated Monthly Flow</h3>
            <ol>
                <li><strong>1st of Month</strong>: Nightly maintenance evaluates shadow experiments</li>
                <li><strong>Promotion</strong>: Experiments meeting criteria (≥52% WR, ≥0.25% ROI, ≤5% DD) are promoted</li>
                <li><strong>Manual Review</strong>: Review promoted experiments on this dashboard</li>
                <li><strong>Deployment</strong>: Use deployment script to apply winning configs</li>
            </ol>
            
            <h3>Deployment Commands</h3>
            <pre>
# Deploy promoted experiments (with automatic backup)
python3 deploy_configs.py

# Rollback to latest backup
python3 deploy_configs.py --rollback

# View deployment status
python3 deploy_configs.py --status
            </pre>
            
            <h3>Safety Features</h3>
            <ul>
                <li>✅ Automatic backup before each deployment</li>
                <li>✅ Timestamped backup files for audit trail</li>
                <li>✅ One-click rollback to previous configuration</li>
                <li>✅ Metrics preserved for each deployed config</li>
            </ul>
        </div>

    </div>
</body>
</html>
    """
    return html


@app.route("/futures")
def futures_dashboard():
    """Futures trading dashboard with leverage, margin, and liquidation monitoring."""
    
    # Load futures data
    leverage_budgets = read_json_log("../configs/leverage_budgets.json") or {"proposals": []}
    margin_report = read_json_log("futures_margin_safety.json") or {"positions": [], "alerts": []}
    fut_attr = read_json_log("futures_attribution.json") or {"summary": []}
    pretrade = read_json_log("futures_pretrade_validation.json") or {}
    blocked = read_json_log("blocked_orders.json") or {}
    kill_log = read_json_log("kill_switch_log.json") or {}
    ladder_events = read_json_log("ladder_exit_events.json") or {"events": []}
    ladder_policies = read_json_log("../configs/ladder_exit_policies.json") or {"defaults": {}, "overrides": []}
    learning_data = read_json_log("ladder_exit_learning.json") or {"recommendations": []}
    
    leverage_proposals = leverage_budgets.get("proposals", [])
    margin_positions = margin_report.get("positions", [])
    margin_alerts = margin_report.get("alerts", [])
    attribution_summary = fut_attr.get("summary", [])
    ladder_exec = ladder_events.get("events", [])
    
    # Calculate ladder stats
    ladder_count = len(ladder_exec)
    ladder_by_reason = {}
    for e in ladder_exec:
        reason = e.get("reason", "unknown")
        ladder_by_reason[reason] = ladder_by_reason.get(reason, 0) + 1
    
    html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Futures Dashboard - Trading Bot</title>
    <meta http-equiv="refresh" content="30">
    <script src="https://cdn.plot.ly/plotly-2.27.0.min.js" charset="utf-8"></script>
    <style>
        body {{ font-family: 'Arial', sans-serif; background: #0a0e27; color: #eee; padding: 20px; margin: 0; }}
        .header {{ background: linear-gradient(135deg, #1e3a8a 0%, #3b82f6 100%); padding: 25px; border-radius: 10px; margin-bottom: 30px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }}
        h1 {{ color: #60a5fa; margin: 0; font-size: 2em; }}
        h2 {{ color: cyan; margin-top: 32px; border-bottom: 2px solid #1e40af; padding-bottom: 8px; }}
        h3 {{ color: #93c5fd; margin-top: 20px; }}
        table {{ border-collapse: collapse; width: 100%; margin-bottom: 18px; background: #1e293b; }}
        th, td {{ border: 1px solid #334155; padding: 10px; text-align: left; }}
        th {{ background: #0f172a; color: #60a5fa; font-weight: bold; }}
        tr:hover {{ background: #293548; }}
        .green {{ color: #10b981; font-weight: bold; }}
        .red {{ color: #ef4444; font-weight: bold; }}
        .yellow {{ color: #fbbf24; font-weight: bold; }}
        .orange {{ color: #f97316; font-weight: bold; }}
        a {{ color: #60a5fa; text-decoration: none; transition: color 0.3s; }}
        a:hover {{ color: #93c5fd; text-decoration: underline; }}
        .section {{ margin-bottom: 28px; padding: 20px; background: #1e293b; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.2); }}
        .stat-card {{ display: inline-block; background: linear-gradient(135deg, #1e3a8a 0%, #3b82f6 100%); padding: 20px; border-radius: 8px; margin: 10px; min-width: 200px; box-shadow: 0 2px 4px rgba(0,0,0,0.2); }}
        .stat-label {{ color: #93c5fd; font-size: 0.9em; margin-bottom: 5px; }}
        .stat-value {{ color: #fff; font-size: 2em; font-weight: bold; }}
        pre {{ background: #0f172a; padding: 15px; border-radius: 5px; overflow-x: auto; border: 1px solid #334155; }}
        code {{ background: #0f172a; padding: 2px 6px; border-radius: 3px; color: #60a5fa; }}
        .back-link {{ background: #1e40af; padding: 10px 20px; border-radius: 5px; display: inline-block; margin-top: 10px; }}
        .alert-box {{ background: #7f1d1d; border-left: 4px solid #ef4444; padding: 15px; margin: 15px 0; border-radius: 4px; }}
        .info-box {{ background: #1e3a8a; border-left: 4px solid #60a5fa; padding: 15px; margin: 15px 0; border-radius: 4px; }}
        .chart-container {{ width: 100%; height: 400px; margin: 20px 0; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>⚙️ Futures Trading Dashboard</h1>
        <p style="margin: 10px 0 0 0; color: #93c5fd;">Leverage, Margin Safety & Liquidation Monitoring</p>
        <div style="margin-top: 15px;">
            <a href="/" class="back-link">⬅️ Main</a>
            <a href="/elite" class="back-link" style="margin-left: 10px;">📊 Elite</a>
            <a href="/deployments" class="back-link" style="margin-left: 10px;">🚀 Deployments</a>
        </div>
    </div>

    <div class="section">
        <div class="stat-card">
            <div class="stat-label">Leverage Proposals</div>
            <div class="stat-value">{len(leverage_proposals)}</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Open Futures Positions</div>
            <div class="stat-value">{len(margin_positions)}</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Margin Alerts</div>
            <div class="stat-value" class="{'red' if len(margin_alerts) > 0 else 'green'}">{len(margin_alerts)}</div>
        </div>
    </div>

    <div class="section">
        <h2>📊 Leverage Budgets (Per Symbol/Strategy/Regime)</h2>
        {"<p style='color: #94a3b8;'>No leverage proposals found. Run leverage allocation to generate budgets.</p>" if not leverage_proposals else ""}
        <table>
            <tr>
                <th>Symbol</th>
                <th>Strategy</th>
                <th>Regime</th>
                <th>Proposed Leverage</th>
                <th>Win Rate Input</th>
                <th>Volatility Index</th>
            </tr>
    """
    
    for p in leverage_proposals:
        inputs = p.get("inputs", {})
        html += f"""
            <tr>
                <td><strong>{p.get('symbol', 'N/A')}</strong></td>
                <td>{p.get('strategy', 'N/A')}</td>
                <td>{p.get('regime', 'N/A')}</td>
                <td class="green"><strong>{p.get('proposed_leverage', 0)}x</strong></td>
                <td>{inputs.get('winrate', 0) * 100:.1f}%</td>
                <td>{inputs.get('volatility_index', 1.0):.2f}</td>
            </tr>
        """
    
    html += """
        </table>
    </div>

    <div class="section">
        <h2>🛡️ Margin Safety Monitor</h2>
    """
    
    if margin_alerts:
        html += f"""
        <div class="alert-box">
            <strong>⚠️ {len(margin_alerts)} MARGIN ALERT(S):</strong> Positions approaching liquidation threshold!
        </div>
        """
    
    html += f"""
        <table>
            <tr>
                <th>Symbol</th>
                <th>Side</th>
                <th>Leverage</th>
                <th>Mark Price</th>
                <th>Liquidation Price</th>
                <th>Buffer %</th>
                <th>Status</th>
            </tr>
    """
    
    for p in margin_positions:
        status = p.get('status', 'OK')
        status_class = 'red' if status == 'REDUCE_EXPOSURE' else ('yellow' if status == 'ALERT' else 'green')
        buffer = p.get('buffer_pct', 0) or 0
        mark_price = p.get('mark_price', 0) or 0
        liq_price = p.get('liquidation_price', 0) or 0
        
        html += f"""
            <tr>
                <td><strong>{p.get('symbol', 'N/A')}</strong></td>
                <td>{p.get('side', 'N/A')}</td>
                <td>{p.get('leverage', 1) or 1}x</td>
                <td>${mark_price:,.2f}</td>
                <td>${liq_price:,.2f}</td>
                <td class="{status_class}">{buffer:.2f}%</td>
                <td class="{status_class}"><strong>{status}</strong></td>
            </tr>
        """
    
    if not margin_positions:
        html += "<tr><td colspan='7' style='text-align: center; color: #94a3b8;'>No open futures positions</td></tr>"
    
    html += """
        </table>
        <p style="color: #94a3b8; margin-top: 10px;">
            <strong>Buffer Thresholds:</strong> 
            <span class="green">OK: >12%</span> | 
            <span class="yellow">ALERT: 8-12%</span> | 
            <span class="red">REDUCE: <8%</span>
        </p>
    </div>

    <div class="section">
        <h2>🏷️ Futures Attribution (Leverage-Adjusted Performance)</h2>
        <table>
            <tr>
                <th>Symbol</th>
                <th>Strategy</th>
                <th>Regime</th>
                <th>Leverage</th>
                <th>ROI</th>
                <th>PnL</th>
                <th>Fees</th>
                <th>Trades</th>
                <th>Timestamp</th>
            </tr>
    """
    
    for r in attribution_summary[-20:]:  # Last 20 trades
        roi_class = 'green' if r.get('roi', 0) > 0 else 'red'
        pnl_class = 'green' if r.get('pnl', 0) > 0 else 'red'
        
        html += f"""
            <tr>
                <td><strong>{r.get('symbol', 'N/A')}</strong></td>
                <td>{r.get('strategy', 'N/A')}</td>
                <td>{r.get('regime', 'N/A')}</td>
                <td>{r.get('leverage', 1)}x</td>
                <td class="{roi_class}">{r.get('roi', 0) * 100:.2f}%</td>
                <td class="{pnl_class}">${r.get('pnl', 0):.2f}</td>
                <td>${r.get('fees', 0):.2f}</td>
                <td>{r.get('trades', 1)}</td>
                <td>{r.get('timestamp', 'N/A')[:19]}</td>
            </tr>
        """
    
    if not attribution_summary:
        html += "<tr><td colspan='9' style='text-align: center; color: #94a3b8;'>No futures trades yet</td></tr>"
    
    html += """
        </table>
    </div>

    <div class="section">
        <h2>🎯 Ladder Exit Strategy (Tiered Profit-Taking)</h2>
    """
    
    defaults = ladder_policies.get("defaults", {})
    tiers = defaults.get("tiers_pct", [0.25, 0.25, 0.5])
    
    html += f"""
        <h3>Default Configuration</h3>
        <p><strong>Tier Split:</strong> {' / '.join([f'{int(t*100)}%' for t in tiers])} | 
        <strong>ATR Multiplier:</strong> {defaults.get('trail_atr_mult', 2.0)}x | 
        <strong>Cooldown:</strong> {defaults.get('cooldown_s', 30)}s | 
        <strong>RR Targets:</strong> {', '.join([f'{r}%' for r in defaults.get('rr_targets', [1.0, 2.0])])}</p>
        
        <h3>Recent Executions ({ladder_count} total)</h3>
        <table>
            <tr>
                <th>Timestamp</th>
                <th>Symbol</th>
                <th>Side</th>
                <th>Tier</th>
                <th>Quantity</th>
                <th>Reason</th>
                <th>Price</th>
            </tr>
    """
    
    for e in ladder_exec[-20:]:
        html += f"""
            <tr>
                <td>{e.get('timestamp', 'N/A')[:19]}</td>
                <td><strong>{e.get('symbol', 'N/A')}</strong></td>
                <td>{e.get('side', 'N/A')}</td>
                <td>T{e.get('tier_index', 0)} ({int(e.get('tier_pct', 0)*100)}%)</td>
                <td>{e.get('qty', 0):.6f}</td>
                <td class="{'green' if 'rr_hit' in e.get('reason', '') else ('red' if 'protective' in e.get('reason', '') or 'trail' in e.get('reason', '') else 'yellow')}">{e.get('reason', 'N/A')}</td>
                <td>${e.get('fill_price', 0):,.2f}</td>
            </tr>
        """
    
    if not ladder_exec:
        html += "<tr><td colspan='7' style='text-align: center; color: #94a3b8;'>No ladder exits executed yet</td></tr>"
    
    html += """
        </table>
        
        <h3>Trigger Distribution</h3>
        <p style="color: #94a3b8;">
    """
    
    for reason, count in sorted(ladder_by_reason.items(), key=lambda x: x[1], reverse=True):
        color = 'green' if 'rr_hit' in reason else ('red' if 'protective' in reason or 'trail' in reason else 'yellow')
        html += f'<span class="{color}"><strong>{reason}:</strong> {count}</span> | '
    
    if not ladder_by_reason:
        html += "No executions yet"
    
    html += """
        </p>
        <p style="color: #94a3b8; margin-top: 15px;">
            <strong>Trigger Types:</strong><br>
            <span class="green">• RR Hit:</span> Profit target reached (1% or 2%)<br>
            <span class="yellow">• Signal Reverse:</span> EMA crossover flip<br>
            <span class="red">• Protective Reduce:</span> Margin buffer <8%<br>
            <span class="red">• Trail Stop:</span> ATR-based trailing stop triggered
        </p>
    </div>
    """
    
    # Prepare chart data
    roi_timestamps = [a.get("timestamp", "")[:19] for a in attribution_summary[-50:]]
    roi_values = [a.get("roi", 0.0) * 100 for a in attribution_summary[-50:]]
    regimes = [a.get("regime", "unknown") for a in attribution_summary[-50:]]
    
    regime_colors = []
    for r in regimes:
        if r == "volatile":
            regime_colors.append("#ef4444")
        elif r == "trending":
            regime_colors.append("#10b981")
        else:
            regime_colors.append("#f97316")
    
    buf_symbols = [p.get("symbol", "") for p in margin_positions]
    buf_values = [p.get("buffer_pct", 0.0) for p in margin_positions]
    
    exit_labels = list(ladder_by_reason.keys()) if ladder_by_reason else ["No Data"]
    exit_values = list(ladder_by_reason.values()) if ladder_by_reason else [1]
    
    recommendations = learning_data.get("recommendations", [])
    rec_current, rec_recommended, rec_labels = [], [], []
    if recommendations:
        rec = recommendations[0]
        rec_labels = [f"Tier {i}" for i in range(len(rec.get("current_tiers_pct", [])))]
        rec_current = [t * 100 for t in rec.get("current_tiers_pct", [])]
        rec_recommended = [t * 100 for t in rec.get("recommended_tiers_pct", [])]
    
    html += f"""
    <div class="section">
        <h2>📊 Interactive Futures Analytics</h2>
        
        <h3>ROI Curve with Market Regime Overlay</h3>
        <div id="roi-curve" class="chart-container"></div>
        <script>
        var roiTrace = {{
            x: {json.dumps(roi_timestamps)},
            y: {json.dumps(roi_values)},
            type: 'scatter',
            mode: 'lines+markers',
            name: 'Futures ROI',
            line: {{color: '#60a5fa', width: 2}},
            marker: {{size: 6, color: '#60a5fa'}}
        }};
        var regimeTrace = {{
            x: {json.dumps(roi_timestamps)},
            y: {json.dumps(roi_values)},
            text: {json.dumps(regimes)},
            mode: 'markers',
            name: 'Market Regime',
            marker: {{
                size: 10,
                color: {json.dumps(regime_colors)},
                line: {{color: '#fff', width: 1}}
            }},
            hovertemplate: '<b>%{{text}}</b><br>ROI: %{{y:.2f}}%<extra></extra>'
        }};
        var roiLayout = {{
            title: {{text: 'Futures ROI with Market Regimes', font: {{color: '#60a5fa'}}}},
            paper_bgcolor: '#0f172a',
            plot_bgcolor: '#1e293b',
            xaxis: {{title: 'Timestamp', gridcolor: '#334155', color: '#93c5fd'}},
            yaxis: {{title: 'ROI (%)', gridcolor: '#334155', color: '#93c5fd'}},
            hovermode: 'closest',
            showlegend: true,
            legend: {{font: {{color: '#93c5fd'}}}}
        }};
        Plotly.newPlot('roi-curve', [roiTrace, regimeTrace], roiLayout, {{responsive: true}});
        </script>
        
        <h3 style="margin-top: 40px;">Margin Buffer Health</h3>
        <div id="buffer-trends" class="chart-container"></div>
        <script>
        var bufferTrace = {{
            x: {json.dumps(buf_symbols)},
            y: {json.dumps(buf_values)},
            type: 'bar',
            name: 'Liquidation Buffer',
            marker: {{
                color: {json.dumps([
                    '#10b981' if b > 12 else ('#fbbf24' if b > 8 else '#ef4444')
                    for b in buf_values
                ])},
                line: {{color: '#fff', width: 1}}
            }},
            text: {json.dumps([f'{{b:.1f}}%' for b in buf_values])},
            textposition: 'auto'
        }};
        var bufferLayout = {{
            title: {{text: 'Margin Safety Buffer by Position', font: {{color: '#60a5fa'}}}},
            paper_bgcolor: '#0f172a',
            plot_bgcolor: '#1e293b',
            xaxis: {{title: 'Symbol', gridcolor: '#334155', color: '#93c5fd'}},
            yaxis: {{title: 'Buffer (%)', gridcolor: '#334155', color: '#93c5fd'}},
            showlegend: false
        }};
        Plotly.newPlot('buffer-trends', [bufferTrace], bufferLayout, {{responsive: true}});
        </script>
        
        <h3 style="margin-top: 40px;">Ladder Exit Distribution</h3>
        <div id="exit-dist" class="chart-container" style="height: 500px;"></div>
        <script>
        var exitPie = {{
            labels: {json.dumps(exit_labels)},
            values: {json.dumps(exit_values)},
            type: 'pie',
            marker: {{
                colors: {json.dumps([
                    '#10b981' if 'rr_hit' in label else 
                    ('#fbbf24' if 'signal' in label else '#ef4444')
                    for label in exit_labels
                ])}
            }},
            textinfo: 'label+percent+value',
            hovertemplate: '<b>%{{label}}</b><br>Count: %{{value}}<br>%{{percent}}<extra></extra>'
        }};
        var exitLayout = {{
            title: {{text: 'Ladder Exit Triggers', font: {{color: '#60a5fa'}}}},
            paper_bgcolor: '#0f172a',
            plot_bgcolor: '#1e293b',
            showlegend: true,
            legend: {{font: {{color: '#93c5fd'}}}}
        }};
        Plotly.newPlot('exit-dist', [exitPie], exitLayout, {{responsive: true}});
        </script>
    """
    
    if rec_labels:
        html += f"""
        <h3 style="margin-top: 40px;">Adaptive Learning: Tier Recommendations</h3>
        <div id="tier-recs" class="chart-container"></div>
        <script>
        var currentTiers = {{
            x: {json.dumps(rec_labels)},
            y: {json.dumps(rec_current)},
            type: 'bar',
            name: 'Current Allocation',
            marker: {{color: '#64748b'}}
        }};
        var recommendedTiers = {{
            x: {json.dumps(rec_labels)},
            y: {json.dumps(rec_recommended)},
            type: 'bar',
            name: 'Recommended (Learned)',
            marker: {{color: '#60a5fa'}}
        }};
        var tierLayout = {{
            title: {{text: 'Adaptive Tier Optimization', font: {{color: '#60a5fa'}}}},
            paper_bgcolor: '#0f172a',
            plot_bgcolor: '#1e293b',
            xaxis: {{title: 'Exit Tier', gridcolor: '#334155', color: '#93c5fd'}},
            yaxis: {{title: 'Allocation (%)', gridcolor: '#334155', color: '#93c5fd'}},
            barmode: 'group',
            showlegend: true,
            legend: {{font: {{color: '#93c5fd'}}}}
        }};
        Plotly.newPlot('tier-recs', [currentTiers, recommendedTiers], tierLayout, {{responsive: true}});
        </script>
        <p style="color: #94a3b8; margin-top: 15px;">
            <strong>Learning Status:</strong> 
            {len(recommendations)} cohort(s) analyzed | 
            Run <code>python3 src/futures_exit_learning.py --optimize</code> to update policies
        </p>
        """
    
    html += """
    </div>

    <div class="section">
        <h2>✅ Pre-Trade Validation (Last Decision)</h2>
        <div class="info-box">
    """
    
    last_decision = pretrade.get("last_decision", {})
    decision_ok = last_decision.get("ok", "N/A")
    
    html += f"""
            <p><strong>Decision:</strong> <span class="{'green' if decision_ok else 'red'}">{decision_ok}</span></p>
            <p><strong>Leverage Cap:</strong> {last_decision.get('cap', 'N/A')}x</p>
            <p><strong>Estimated Buffer:</strong> {last_decision.get('buffer_est_pct', 'N/A')}%</p>
            <p><strong>Reasons:</strong> {', '.join(last_decision.get('reasons', [])) if last_decision.get('reasons') else 'None'}</p>
            <p><strong>Timestamp:</strong> {pretrade.get('timestamp', 'N/A')[:19]}</p>
        </div>
    </div>

    <div class="section">
        <h2>🧱 Blocked Orders (Risk Prevention)</h2>
        <pre>{json.dumps(blocked, indent=2) if blocked else 'No blocked orders'}</pre>
    </div>

    <div class="section">
        <h2>🛑 Kill Switch Activity (Emergency Flatten)</h2>
        <pre>{json.dumps(kill_log, indent=2) if kill_log else 'No kill switch activations'}</pre>
        <p style="color: #94a3b8; margin-top: 10px;">
            <strong>Note:</strong> Kill switch flattens all futures positions immediately via market orders. 
            Use only in emergencies.
        </p>
    </div>

    <div class="section" style="background: #1e3a8a; padding: 20px;">
        <h2 style="color: #93c5fd;">🔐 Futures Trading Safety Features</h2>
        <ul style="line-height: 1.8;">
            <li>✅ <strong>Pre-Trade Validation:</strong> All orders checked against leverage caps and liquidation buffer before execution</li>
            <li>✅ <strong>Margin Safety Monitor:</strong> Real-time liquidation buffer tracking with automatic alerts</li>
            <li>✅ <strong>Leverage Allocation:</strong> Dynamic leverage budgets based on strategy performance and regime</li>
            <li>✅ <strong>Ladder Exits:</strong> Tiered profit-taking with RR targets, signal reversals, and trailing stops</li>
            <li>✅ <strong>Emergency De-Leveraging:</strong> Automatic position reduction when margin ratio deteriorates</li>
            <li>✅ <strong>Kill Switch:</strong> One-command emergency flatten for all futures positions</li>
            <li>✅ <strong>Separate Attribution:</strong> Futures performance tracked independently from spot trading</li>
        </ul>
    </div>

    <p style="text-align: center; margin-top: 30px; color: #64748b;">
        Dashboard auto-refreshes every 30 seconds | Last updated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    </p>
</body>
</html>
    """
    
    return html


@app.route("/trigger-optimization", methods=["POST", "GET"])
def trigger_optimization():
    """Endpoint to trigger nightly optimization remotely."""
    import subprocess
    from datetime import datetime
    
    try:
        # Run optimization script in background
        script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "nightly_optimization.sh")
        
        # Log the trigger
        log_msg = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Optimization triggered via web endpoint\n"
        log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs", "optimization")
        os.makedirs(log_dir, exist_ok=True)
        
        with open(os.path.join(log_dir, "web_triggers.log"), "a") as f:
            f.write(log_msg)
        
        # Run in background (don't wait for completion)
        subprocess.Popen(["/bin/bash", script_path], 
                        stdout=subprocess.PIPE, 
                        stderr=subprocess.PIPE)
        
        return jsonify({
            "status": "success",
            "message": "Optimization started. Bot will auto-restart within 60 seconds.",
            "timestamp": datetime.now().isoformat()
        }), 200
        
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
            "timestamp": datetime.now().isoformat()
        }), 500


@app.route("/api/direction-router/status")
def direction_router_status():
    """Get Regime-Aware Direction Router status and metrics."""
    try:
        from src.regime_direction_router import get_direction_router
        router = get_direction_router()
        summary = router.get_regime_summary()
        
        return jsonify({
            "status": "success",
            "data": summary
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


@app.route("/direction-router")
def direction_router_dashboard():
    """Regime-Aware Direction Router dashboard page."""
    try:
        from src.regime_direction_router import get_direction_router
        router = get_direction_router()
        summary = router.get_regime_summary()
        
        directions_html = ""
        for sig, dirs in summary.get('current_directions', {}).items():
            ewma = summary.get('ewma_ev', {}).get(sig, {})
            long_ev = ewma.get('LONG', 0)
            short_ev = ewma.get('SHORT', 0)
            samples = summary.get('sample_counts', {}).get(sig, {})
            
            if dirs == ['SHORT']:
                dir_badge = '<span style="color:#ff6600">SHORT only</span>'
            elif dirs == ['LONG']:
                dir_badge = '<span style="color:#00aaff">LONG only</span>'
            elif dirs == []:
                dir_badge = '<span style="color:#ff0000">DISABLED</span>'
            else:
                dir_badge = '<span style="color:#00ff00">BOTH</span>'
            
            directions_html += f"""
            <tr>
                <td>{sig}</td>
                <td>{dir_badge}</td>
                <td style="color:{'#00ff00' if long_ev > 0 else '#ff0000'}">{long_ev:+.1f}bps</td>
                <td style="color:{'#00ff00' if short_ev > 0 else '#ff0000'}">{short_ev:+.1f}bps</td>
                <td>{samples.get('LONG', 0)}</td>
                <td>{samples.get('SHORT', 0)}</td>
            </tr>"""
        
        pending_html = ""
        for sig, pending in summary.get('pending_flips', {}).items():
            pending_html += f"""
            <tr>
                <td>{sig}</td>
                <td>{pending.get('recommended')}</td>
                <td>{pending.get('persistence_count', 0)}/{2}</td>
                <td>{pending.get('reason', '')[:50]}</td>
            </tr>"""
        
        if not pending_html:
            pending_html = "<tr><td colspan='4'>No pending direction changes</td></tr>"
        
        flips_html = ""
        for flip in reversed(summary.get('recent_flips', [])[-5:]):
            flips_html += f"""
            <tr>
                <td>{flip.get('ts', '')[:16]}</td>
                <td>{flip.get('signal', '')}</td>
                <td>{flip.get('from')} → {flip.get('to')}</td>
                <td>{flip.get('reason', '')[:40]}</td>
            </tr>"""
        
        if not flips_html:
            flips_html = "<tr><td colspan='4'>No direction changes yet</td></tr>"
        
        regime = summary.get('regime_bias', 'NEUTRAL')
        total_long = summary.get('total_ev', {}).get('LONG', 0)
        total_short = summary.get('total_ev', {}).get('SHORT', 0)
        
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Direction Router - Regime-Aware Adaptation</title>
    <meta http-equiv="refresh" content="30">
    <style>
        body {{ font-family: monospace; background: #0a0a0a; color: #00ff00; padding: 20px; }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        .header {{ border-bottom: 2px solid #00ff00; padding-bottom: 10px; margin-bottom: 20px; }}
        .regime-badge {{ font-size: 24px; padding: 10px 20px; border-radius: 5px; display: inline-block; margin: 10px 0; }}
        .regime-short {{ background: #ff6600; color: #000; }}
        .regime-long {{ background: #00aaff; color: #000; }}
        .regime-neutral {{ background: #888; color: #000; }}
        .status-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 15px; margin-bottom: 20px; }}
        .status-card {{ background: #1a1a1a; border: 1px solid #00ff00; padding: 15px; border-radius: 5px; }}
        .status-card h3 {{ margin-top: 0; color: #00ff00; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
        th, td {{ border: 1px solid #333; padding: 8px; text-align: left; }}
        th {{ background: #1a1a1a; color: #00ff00; }}
        .ev-positive {{ color: #00ff00; }}
        .ev-negative {{ color: #ff0000; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🔄 Regime-Aware Direction Router</h1>
            <p>Dynamic signal direction adaptation based on rolling window EV analysis</p>
            <div class="regime-badge regime-{'short' if 'SHORT' in regime else ('long' if 'LONG' in regime else 'neutral')}">
                Current Regime: {regime}
            </div>
            <p>Total EV: LONG={total_long:+.1f}bps | SHORT={total_short:+.1f}bps</p>
        </div>
        
        <div class="status-grid">
            <div class="status-card">
                <h3>📊 Signal Direction Rules</h3>
                <table>
                    <tr>
                        <th>Signal</th>
                        <th>Allowed</th>
                        <th>LONG EV</th>
                        <th>SHORT EV</th>
                        <th>L Samples</th>
                        <th>S Samples</th>
                    </tr>
                    {directions_html}
                </table>
            </div>
            
            <div class="status-card">
                <h3>⏳ Pending Direction Changes</h3>
                <p>Requires 2 consecutive evaluations to apply</p>
                <table>
                    <tr>
                        <th>Signal</th>
                        <th>Proposed</th>
                        <th>Persistence</th>
                        <th>Reason</th>
                    </tr>
                    {pending_html}
                </table>
            </div>
        </div>
        
        <div class="status-card">
            <h3>📜 Recent Direction Changes</h3>
            <table>
                <tr>
                    <th>Time</th>
                    <th>Signal</th>
                    <th>Change</th>
                    <th>Reason</th>
                </tr>
                {flips_html}
            </table>
        </div>
        
        <p style="margin-top: 20px; color: #888;">
            Last Updated: {summary.get('last_update', 'N/A')}<br>
            Window Size: 300 samples | Min Samples: 50 | EV Delta Threshold: 5bps | Persistence Required: 2
        </p>
    </div>
</body>
</html>"""
        
        return html
    except Exception as e:
        return f"Error loading direction router dashboard: {e}", 500


@app.route("/api/phase2/status")
def phase2_status():
    """Get Phase 2 status and metrics."""
    try:
        from src.phase2_integration import get_phase2_controller
        controller = get_phase2_controller()
        
        status = controller.get_status()
        
        # Add telemetry summary
        block_summary = controller.telemetry.get_block_summary()
        recent_audits = controller.telemetry.get_recent_audits(limit=10)
        
        return jsonify({
            "status": "success",
            "data": {
                **status,
                "blocking_summary": block_summary,
                "recent_audits": recent_audits
            }
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


@app.route("/phase2")
def phase2_dashboard():
    """Phase 2 dashboard page."""
    try:
        from src.phase2_integration import get_phase2_controller
        controller = get_phase2_controller()
        
        status = controller.get_status()
        block_summary = controller.telemetry.get_block_summary()
        
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Phase 2 Dashboard - Capital Protection</title>
    <meta http-equiv="refresh" content="30">
    <style>
        body {{ font-family: monospace; background: #0a0a0a; color: #00ff00; padding: 20px; }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        .header {{ border-bottom: 2px solid #00ff00; padding-bottom: 10px; margin-bottom: 20px; }}
        .status-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 15px; margin-bottom: 20px; }}
        .status-card {{ background: #1a1a1a; border: 1px solid #00ff00; padding: 15px; border-radius: 5px; }}
        .status-card h3 {{ margin-top: 0; color: #00ff00; }}
        .metric {{ margin: 8px 0; }}
        .metric-label {{ color: #888; display: inline-block; width: 150px; }}
        .metric-value {{ color: #00ff00; font-weight: bold; }}
        .active {{ color: #00ff00; }}
        .inactive {{ color: #ff6600; }}
        .blocked {{ color: #ff0000; }}
        .table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
        .table th, .table td {{ border: 1px solid #333; padding: 8px; text-align: left; }}
        .table th {{ background: #1a1a1a; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>⚡ PHASE 2: Capital Protection → Edge Compounding</h1>
            <p>Statistical Validation | Shadow Mode | Promotion Gates</p>
        </div>
        
        <div class="status-grid">
            <div class="status-card">
                <h3>🎯 Mode</h3>
                <div class="metric">
                    <span class="metric-label">Trading Mode:</span>
                    <span class="metric-value {'active' if status['shadow_mode'] else 'inactive'}">
                        {'SHADOW' if status['shadow_mode'] else 'LIVE'}
                    </span>
                </div>
                <div class="metric">
                    <span class="metric-label">Kill Switch:</span>
                    <span class="metric-value {'blocked' if status['kill_switch'] else 'active'}">
                        {'ACTIVE' if status['kill_switch'] else 'OFF'}
                    </span>
                </div>
            </div>
            
            <div class="status-card">
                <h3>📊 Risk Throttle</h3>
                <div class="metric">
                    <span class="metric-label">Status:</span>
                    <span class="metric-value {'active' if status['throttle']['active'] else 'inactive'}">
                        {'ACTIVE' if status['throttle']['active'] else 'ACCUMULATING'}
                    </span>
                </div>
                <div class="metric">
                    <span class="metric-label">Sharpe:</span>
                    <span class="metric-value">{status['throttle']['sharpe'] or 'N/A'}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Sortino:</span>
                    <span class="metric-value">{status['throttle']['sortino'] or 'N/A'}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Snapshots:</span>
                    <span class="metric-value">{status['throttle']['snapshots']}/10</span>
                </div>
            </div>
            
            <div class="status-card">
                <h3>💰 Portfolio</h3>
                <div class="metric">
                    <span class="metric-label">Value:</span>
                    <span class="metric-value">${status['portfolio']['value']:.2f}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Daily P&L:</span>
                    <span class="metric-value">{status['portfolio']['daily_pnl_bps']:.1f} bps</span>
                </div>
            </div>
            
            <div class="status-card">
                <h3>⚡ Leverage</h3>
                <div class="metric">
                    <span class="metric-label">Max Allowed:</span>
                    <span class="metric-value">{status['leverage']['max_allowed']:.1f}x</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Live Cap:</span>
                    <span class="metric-value">{status['leverage']['live_cap']:.1f}x</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Shadow Cap:</span>
                    <span class="metric-value">{status['leverage']['shadow_cap']:.1f}x</span>
                </div>
            </div>
        </div>
        
        <div class="status-card">
            <h3>🚫 Signal Blocking</h3>
            <div class="metric">
                <span class="metric-label">Total Signals:</span>
                <span class="metric-value">{status['blocking']['total']}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Blocked:</span>
                <span class="metric-value">{status['blocking']['blocked']}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Block Rate:</span>
                <span class="metric-value">{status['blocking']['pct']:.1f}%</span>
            </div>
            
            <h4>Top Block Reasons:</h4>
            <table class="table">
                <tr><th>Reason</th><th>Count</th></tr>
"""
        
        for reason, count in list(block_summary.get('top_10_reasons', {}).items())[:10]:
            html += f"<tr><td>{reason}</td><td>{count}</td></tr>\n"
        
        html += """
            </table>
        </div>
        
        <p style="text-align: center; color: #666; margin-top: 30px;">
            Phase 2 Dashboard | Auto-refresh 30s | Statistical validation for capital protection
        </p>
    </div>
</body>
</html>
        """
        
        return html
        
    except Exception as e:
        return f"<html><body><h1>Error loading Phase 2 dashboard</h1><p>{str(e)}</p></body></html>"


@app.route("/api/phase3/status")
def phase3_status():
    """Get Phase 3 status and metrics."""
    try:
        from src.phase3_integration import get_phase3_controller
        controller = get_phase3_controller()
        
        status = controller.get_status()
        
        return jsonify({
            "status": "success",
            "data": status
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


@app.route("/phase71")
def phase71_dashboard():
    """Phase 7.1 Predictive Stability dashboard page."""
    try:
        from src.phase71_predictive_stability import get_phase71
        engine = get_phase71()
        status = engine.get_status()
        
        cfg = status.get("config", {})
        regime = status.get("regime", {})
        hyst_event = status.get("hysteresis_event") or {}
        rate_limits = status.get("rate_limits", {})
        exit_adj = status.get("exit_adjustments", {})
        routing = status.get("routing_decisions", {})
        
        regime_name = regime.get("name", "N/A")
        regime_conf = regime.get("confidence", 0)
        regime_samples = regime.get("samples", 0)
        
        regime_stats = rate_limits.get("regime", {})
        spread_stats = rate_limits.get("spread", {})
        
        exit_stats = exit_adj.get("stats", {})
        route_stats = routing.get("stats", {})
        
        total_exits = sum(exit_stats.values())
        total_routes = sum(route_stats.values())
        
        hyst_rows = ""
        if hyst_event:
            event_type = hyst_event.get("event", "N/A")
            from_regime = hyst_event.get("from", "N/A")
            to_regime = hyst_event.get("to", "N/A")
            conf = hyst_event.get("conf", 0)
            ts = hyst_event.get("ts", 0)
            import datetime
            ts_str = datetime.datetime.fromtimestamp(ts).strftime("%H:%M:%S") if ts else "N/A"
            hyst_rows = f"""
            <tr>
                <td>{event_type}</td>
                <td>{from_regime}</td>
                <td>{to_regime}</td>
                <td>{conf:.3f}</td>
                <td>{ts_str}</td>
            </tr>
            """
        else:
            hyst_rows = "<tr><td colspan='5' style='text-align:center;color:#8b95a5;'>No hysteresis events yet</td></tr>"
        
        exit_adj_rows = ""
        recent_exits = exit_adj.get("recent", [])
        for adj in recent_exits[-10:]:
            symbol = adj.get("symbol", "N/A")
            adjustment = adj.get("adjustment", "N/A")
            reason = adj.get("reason", "N/A")
            ts = adj.get("ts", 0)
            import datetime
            ts_str = datetime.datetime.fromtimestamp(ts).strftime("%H:%M:%S") if ts else "N/A"
            adj_class = "positive" if adjustment == "relax" else "neutral" if adjustment == "tighten" else "negative"
            exit_adj_rows += f"""
            <tr>
                <td>{symbol}</td>
                <td class="{adj_class}">{adjustment.upper()}</td>
                <td style="font-size:0.9em;">{reason}</td>
                <td>{ts_str}</td>
            </tr>
            """
        if not exit_adj_rows:
            exit_adj_rows = "<tr><td colspan='4' style='text-align:center;color:#8b95a5;'>No exit adjustments yet</td></tr>"
        
        route_rows = ""
        recent_routes = routing.get("recent", [])
        for route in recent_routes[-10:]:
            symbol = route.get("symbol", "N/A")
            route_type = route.get("route", "N/A")
            spread = route.get("spread_bps", 0)
            ts = route.get("ts", 0)
            import datetime
            ts_str = datetime.datetime.fromtimestamp(ts).strftime("%H:%M:%S") if ts else "N/A"
            route_class = "positive" if route_type == "maker" else "neutral" if route_type == "taker" else "negative"
            route_rows += f"""
            <tr>
                <td>{symbol}</td>
                <td class="{route_class}">{route_type.upper()}</td>
                <td>{spread:.2f}</td>
                <td>{ts_str}</td>
            </tr>
            """
        if not route_rows:
            route_rows = "<tr><td colspan='4' style='text-align:center;color:#8b95a5;'>No routing decisions yet</td></tr>"
        
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Phase 7.1 Dashboard</title>
    <meta http-equiv="refresh" content="30">
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #0a0e27; color: #e0e6ed; padding: 20px; margin: 0; }}
        .container {{ max-width: 1600px; margin: 0 auto; }}
        h1 {{ color: #00d4ff; margin-bottom: 10px; font-size: 2.5em; }}
        h2 {{ color: #00d4ff; margin-top: 30px; margin-bottom: 15px; padding-bottom: 10px; border-bottom: 2px solid #00d4ff; }}
        .header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px; }}
        .back-link {{ background: #1e2749; padding: 10px 20px; border-radius: 5px; text-decoration: none; color: #00d4ff; }}
        .back-link:hover {{ background: #2a3558; }}
        .stat-card {{ display: inline-block; background: #1e2749; padding: 15px 25px; margin: 10px 10px 10px 0; border-radius: 8px; min-width: 180px; }}
        .stat-label {{ color: #8b95a5; font-size: 0.9em; margin-bottom: 5px; }}
        .stat-value {{ color: #00d4ff; font-size: 1.8em; font-weight: bold; }}
        table {{ border-collapse: collapse; width: 100%; margin-top: 20px; background: #161b33; border-radius: 8px; overflow: hidden; }}
        th, td {{ border: 1px solid #2a3558; padding: 12px; text-align: left; }}
        th {{ background: #1e2749; color: #00d4ff; font-weight: 600; }}
        tr:hover {{ background: #1a1f3a; }}
        .positive {{ color: #00ff88; font-weight: bold; }}
        .negative {{ color: #ff4466; font-weight: bold; }}
        .neutral {{ color: #ffa500; font-weight: bold; }}
        .section {{ background: #0f1428; padding: 25px; border-radius: 10px; margin-bottom: 30px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>⚡ Phase 7.1: Predictive Stability</h1>
            <div>
                <a href="/phase71/export-html" class="back-link" style="margin-right: 10px;">📄 Download HTML</a>
                <a href="/phase71/export" class="back-link" style="margin-right: 10px;">📥 Download JSON</a>
                <a href="/" class="back-link">← Back to Main Dashboard</a>
            </div>
        </div>
        
        <div class="section">
            <h2>📊 Current Regime Status</h2>
            <div class="grid">
                <div class="stat-card">
                    <div class="stat-label">Regime Name</div>
                    <div class="stat-value">{regime_name}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Confidence</div>
                    <div class="stat-value">{regime_conf:.3f}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Samples</div>
                    <div class="stat-value">{regime_samples}</div>
                </div>
            </div>
        </div>
        
        <div class="section">
            <h2>🔄 Hysteresis Events</h2>
            <table>
                <thead>
                    <tr>
                        <th>Event</th>
                        <th>From</th>
                        <th>To</th>
                        <th>Confidence</th>
                        <th>Time</th>
                    </tr>
                </thead>
                <tbody>
                    {hyst_rows}
                </tbody>
            </table>
        </div>
        
        <div class="section">
            <h2>⏱️ Rate Limiter Stats</h2>
            <div class="grid">
                <div class="stat-card">
                    <div class="stat-label">Regime Allowed</div>
                    <div class="stat-value">{regime_stats.get('allowed', 0)}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Regime Denied</div>
                    <div class="stat-value">{regime_stats.get('denied', 0)}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Regime Allow Rate</div>
                    <div class="stat-value">{regime_stats.get('allow_rate_pct', 0):.1f}%</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Spread Allowed</div>
                    <div class="stat-value">{spread_stats.get('allowed', 0)}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Spread Denied</div>
                    <div class="stat-value">{spread_stats.get('denied', 0)}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Spread Allow Rate</div>
                    <div class="stat-value">{spread_stats.get('allow_rate_pct', 0):.1f}%</div>
                </div>
            </div>
        </div>
        
        <div class="section">
            <h2>📉 Exit Adjustments</h2>
            <div class="grid">
                <div class="stat-card">
                    <div class="stat-label">Tightened</div>
                    <div class="stat-value">{exit_stats.get('tighten', 0)}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Relaxed</div>
                    <div class="stat-value">{exit_stats.get('relax', 0)}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Total</div>
                    <div class="stat-value">{total_exits}</div>
                </div>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>Symbol</th>
                        <th>Adjustment</th>
                        <th>Reason</th>
                        <th>Time</th>
                    </tr>
                </thead>
                <tbody>
                    {exit_adj_rows}
                </tbody>
            </table>
        </div>
        
        <div class="section">
            <h2>🎯 Routing Decisions</h2>
            <div class="grid">
                <div class="stat-card">
                    <div class="stat-label">Maker</div>
                    <div class="stat-value">{route_stats.get('maker', 0)}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Taker</div>
                    <div class="stat-value">{route_stats.get('taker', 0)}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Skipped</div>
                    <div class="stat-value">{route_stats.get('skip', 0)}</div>
                </div>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>Symbol</th>
                        <th>Route</th>
                        <th>Spread (bps)</th>
                        <th>Time</th>
                    </tr>
                </thead>
                <tbody>
                    {route_rows}
                </tbody>
            </table>
        </div>
        
        <div class="section">
            <p style="color: #8b95a5; font-size: 0.9em;">
                <strong>Phase 7.1</strong> adds predictive stability through regime hysteresis (commit/release bands),
                token-bucket rate limiting for regime/spread calls, refined execution routing, and adaptive exit adjustments
                that tighten in deteriorating microstructure or relax in favorable conditions.
            </p>
        </div>
    </div>
</body>
</html>
        """
        
        return html
        
    except Exception as e:
        import traceback
        return f"<pre>Phase 7.1 Dashboard Error: {str(e)}\n\n{traceback.format_exc()}</pre>"


@app.route("/phase71/export")
def phase71_export():
    """Export Phase 7.1 data as downloadable JSON."""
    try:
        from src.phase71_predictive_stability import get_phase71
        import datetime
        
        engine = get_phase71()
        status = engine.get_status()
        
        export_data = {
            "export_timestamp": datetime.datetime.now().isoformat(),
            "phase": "7.1 - Predictive Stability",
            "config": status.get("config", {}),
            "current_regime": status.get("regime", {}),
            "hysteresis_event": status.get("hysteresis_event"),
            "rate_limiters": status.get("rate_limits", {}),
            "exit_adjustments": status.get("exit_adjustments", {}),
            "routing_decisions": status.get("routing_decisions", {}),
            "telemetry_history": status.get("telemetry_history", [])
        }
        
        from flask import Response
        import json
        
        json_data = json.dumps(export_data, indent=2)
        
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"phase71_export_{timestamp}.json"
        
        return Response(
            json_data,
            mimetype="application/json",
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )
        
    except Exception as e:
        import traceback
        return f"<pre>Export Error: {str(e)}\n\n{traceback.format_exc()}</pre>", 500


@app.route("/phase71/export-html")
def phase71_export_html():
    """Export Phase 7.1 dashboard as downloadable HTML file."""
    try:
        from src.phase71_predictive_stability import get_phase71
        import datetime
        
        engine = get_phase71()
        status = engine.get_status()
        
        cfg = status.get("config", {})
        regime = status.get("regime", {})
        hyst_event = status.get("hysteresis_event") or {}
        rate_limits = status.get("rate_limits", {})
        exit_adj = status.get("exit_adjustments", {})
        routing = status.get("routing_decisions", {})
        
        regime_name = regime.get("name", "N/A")
        regime_conf = regime.get("confidence", 0)
        regime_samples = regime.get("samples", 0)
        
        regime_stats = rate_limits.get("regime", {})
        spread_stats = rate_limits.get("spread", {})
        
        exit_stats = exit_adj.get("stats", {})
        route_stats = routing.get("stats", {})
        
        total_exits = sum(exit_stats.values())
        total_routes = sum(route_stats.values())
        
        hyst_rows = ""
        if hyst_event:
            event_type = hyst_event.get("event", "N/A")
            from_regime = hyst_event.get("from", "N/A")
            to_regime = hyst_event.get("to", "N/A")
            conf = hyst_event.get("conf", 0)
            ts = hyst_event.get("ts", 0)
            ts_str = datetime.datetime.fromtimestamp(ts).strftime("%H:%M:%S") if ts else "N/A"
            hyst_rows = f"""
            <tr>
                <td>{event_type}</td>
                <td>{from_regime}</td>
                <td>{to_regime}</td>
                <td>{conf:.3f}</td>
                <td>{ts_str}</td>
            </tr>
            """
        else:
            hyst_rows = "<tr><td colspan='5' style='text-align:center;color:#8b95a5;'>No hysteresis events yet</td></tr>"
        
        exit_adj_rows = ""
        recent_exits = exit_adj.get("recent", [])
        for adj in recent_exits[-10:]:
            symbol = adj.get("symbol", "N/A")
            adjustment = adj.get("adjustment", "N/A")
            reason = adj.get("reason", "N/A")
            ts = adj.get("ts", 0)
            ts_str = datetime.datetime.fromtimestamp(ts).strftime("%H:%M:%S") if ts else "N/A"
            adj_class = "positive" if adjustment == "relax" else "neutral" if adjustment == "tighten" else "negative"
            exit_adj_rows += f"""
            <tr>
                <td>{symbol}</td>
                <td class="{adj_class}">{adjustment.upper()}</td>
                <td style="font-size:0.9em;">{reason}</td>
                <td>{ts_str}</td>
            </tr>
            """
        if not exit_adj_rows:
            exit_adj_rows = "<tr><td colspan='4' style='text-align:center;color:#8b95a5;'>No exit adjustments yet</td></tr>"
        
        route_rows = ""
        recent_routes = routing.get("recent", [])
        for route in recent_routes[-10:]:
            symbol = route.get("symbol", "N/A")
            route_type = route.get("route", "N/A")
            spread = route.get("spread_bps", 0)
            ts = route.get("ts", 0)
            ts_str = datetime.datetime.fromtimestamp(ts).strftime("%H:%M:%S") if ts else "N/A"
            route_class = "positive" if route_type == "maker" else "neutral" if route_type == "taker" else "negative"
            route_rows += f"""
            <tr>
                <td>{symbol}</td>
                <td class="{route_class}">{route_type.upper()}</td>
                <td>{spread:.2f}</td>
                <td>{ts_str}</td>
            </tr>
            """
        if not route_rows:
            route_rows = "<tr><td colspan='4' style='text-align:center;color:#8b95a5;'>No routing decisions yet</td></tr>"
        
        export_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Phase 7.1 Dashboard - Exported {export_time}</title>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #0a0e27; color: #e0e6ed; padding: 20px; margin: 0; }}
        .container {{ max-width: 1600px; margin: 0 auto; }}
        h1 {{ color: #00d4ff; margin-bottom: 10px; font-size: 2.5em; }}
        h2 {{ color: #00d4ff; margin-top: 30px; margin-bottom: 15px; padding-bottom: 10px; border-bottom: 2px solid #00d4ff; }}
        .header {{ margin-bottom: 30px; }}
        .export-info {{ background: #1e2749; padding: 15px; border-radius: 5px; margin-bottom: 20px; color: #8b95a5; }}
        .stat-card {{ display: inline-block; background: #1e2749; padding: 15px 25px; margin: 10px 10px 10px 0; border-radius: 8px; min-width: 180px; }}
        .stat-label {{ color: #8b95a5; font-size: 0.9em; margin-bottom: 5px; }}
        .stat-value {{ color: #00d4ff; font-size: 1.8em; font-weight: bold; }}
        table {{ border-collapse: collapse; width: 100%; margin-top: 20px; background: #161b33; border-radius: 8px; overflow: hidden; }}
        th, td {{ border: 1px solid #2a3558; padding: 12px; text-align: left; }}
        th {{ background: #1e2749; color: #00d4ff; font-weight: 600; }}
        tr:hover {{ background: #1a1f3a; }}
        .positive {{ color: #00ff88; font-weight: bold; }}
        .negative {{ color: #ff4466; font-weight: bold; }}
        .neutral {{ color: #ffa500; font-weight: bold; }}
        .section {{ background: #0f1428; padding: 25px; border-radius: 10px; margin-bottom: 30px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>⚡ Phase 7.1: Predictive Stability</h1>
            <div class="export-info">
                <strong>Exported:</strong> {export_time} | 
                <strong>Source:</strong> Crypto Trading Bot Phase 7.1 Module
            </div>
        </div>
        
        <div class="section">
            <h2>📊 Current Regime Status</h2>
            <div class="grid">
                <div class="stat-card">
                    <div class="stat-label">Regime Name</div>
                    <div class="stat-value">{regime_name}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Confidence</div>
                    <div class="stat-value">{regime_conf:.3f}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Samples</div>
                    <div class="stat-value">{regime_samples}</div>
                </div>
            </div>
        </div>
        
        <div class="section">
            <h2>🔄 Hysteresis Events</h2>
            <table>
                <thead>
                    <tr>
                        <th>Event</th>
                        <th>From</th>
                        <th>To</th>
                        <th>Confidence</th>
                        <th>Time</th>
                    </tr>
                </thead>
                <tbody>
                    {hyst_rows}
                </tbody>
            </table>
        </div>
        
        <div class="section">
            <h2>⏱️ Rate Limiter Stats</h2>
            <div class="grid">
                <div class="stat-card">
                    <div class="stat-label">Regime Allowed</div>
                    <div class="stat-value">{regime_stats.get('allowed', 0)}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Regime Denied</div>
                    <div class="stat-value">{regime_stats.get('denied', 0)}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Regime Allow Rate</div>
                    <div class="stat-value">{regime_stats.get('allow_rate_pct', 0):.1f}%</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Spread Allowed</div>
                    <div class="stat-value">{spread_stats.get('allowed', 0)}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Spread Denied</div>
                    <div class="stat-value">{spread_stats.get('denied', 0)}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Spread Allow Rate</div>
                    <div class="stat-value">{spread_stats.get('allow_rate_pct', 0):.1f}%</div>
                </div>
            </div>
        </div>
        
        <div class="section">
            <h2>📉 Exit Adjustments</h2>
            <div class="grid">
                <div class="stat-card">
                    <div class="stat-label">Tightened</div>
                    <div class="stat-value">{exit_stats.get('tighten', 0)}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Relaxed</div>
                    <div class="stat-value">{exit_stats.get('relax', 0)}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Total</div>
                    <div class="stat-value">{total_exits}</div>
                </div>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>Symbol</th>
                        <th>Adjustment</th>
                        <th>Reason</th>
                        <th>Time</th>
                    </tr>
                </thead>
                <tbody>
                    {exit_adj_rows}
                </tbody>
            </table>
        </div>
        
        <div class="section">
            <h2>🎯 Routing Decisions</h2>
            <div class="grid">
                <div class="stat-card">
                    <div class="stat-label">Maker</div>
                    <div class="stat-value">{route_stats.get('maker', 0)}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Taker</div>
                    <div class="stat-value">{route_stats.get('taker', 0)}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Skipped</div>
                    <div class="stat-value">{route_stats.get('skip', 0)}</div>
                </div>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>Symbol</th>
                        <th>Route</th>
                        <th>Spread (bps)</th>
                        <th>Time</th>
                    </tr>
                </thead>
                <tbody>
                    {route_rows}
                </tbody>
            </table>
        </div>
        
        <div class="section">
            <p style="color: #8b95a5; font-size: 0.9em;">
                <strong>Phase 7.1</strong> adds predictive stability through regime hysteresis (commit/release bands),
                token-bucket rate limiting for regime/spread calls, refined execution routing, and adaptive exit adjustments
                that tighten in deteriorating microstructure or relax in favorable conditions.
            </p>
        </div>
    </div>
</body>
</html>
"""
        
        from flask import Response
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"phase71_dashboard_{timestamp}.html"
        
        return Response(
            html,
            mimetype="text/html",
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )
        
    except Exception as e:
        import traceback
        return f"<pre>HTML Export Error: {str(e)}\n\n{traceback.format_exc()}</pre>", 500


@app.route("/phase8")
def phase8_dashboard():
    """Phase 8: Trader Dashboard - P&L-first, clean, fast."""
    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<title>Trader Dashboard — P&L, Active, History</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
  body { font-family: system-ui, Arial, sans-serif; margin: 20px; background: #0f1218; color: #e6e6e6; }
  .header { display:flex; align-items:center; gap:12px; flex-wrap:wrap; }
  .card { background:#151a23; padding:16px; border-radius:8px; margin-bottom:16px; }
  .row { display:flex; gap:16px; flex-wrap:wrap; }
  .col { flex:1; min-width:300px; }
  table { width:100%; border-collapse:collapse; }
  th, td { padding:8px; border-bottom:1px solid #222836; text-align:left; }
  .green { color:#25d160; }
  .red { color:#ff4d4d; }
  .muted { color:#9aa0a6; }
  .pill { padding:4px 8px; border-radius:999px; background:#222836; color:#9aa0a6; }
  .tf { padding:6px; border-radius:6px; background:#1a202c; color:#e6e6e6; border:1px solid #2b3240; }
  .back-link { padding:6px 12px; border-radius:6px; background:#1a202c; color:#00d4ff; text-decoration:none; border:1px solid #2b3240; }
  .back-link:hover { background:#2a3558; }
  canvas { width:100%; height:160px; background:#0f1218; border:1px solid #222836; border-radius:8px; }
</style>
</head>
<body>
  <div class="header">
    <h2>Trader Dashboard</h2>
    <span id="env-badge" class="pill">ENV: —</span>
    <span id="updated" class="pill">Updated: —</span>
    <select id="venue" class="tf">
      <option value="all" selected>All Trades</option>
      <option value="spot">Spot Only</option>
      <option value="futures">Futures Only</option>
    </select>
    <select id="tf" class="tf">
      <option value="1D" selected>1D</option>
      <option value="7D">7D</option>
      <option value="30D">30D</option>
      <option value="YTD">YTD</option>
      <option value="ALL">ALL</option>
    </select>
    <a href="/bots" class="back-link" style="background: linear-gradient(135deg, #1a4d2e 0%, #2d5a3d 100%); border-color: #00ff88;">Alpha vs Beta</a>
    <a href="/futures" class="back-link">Futures</a>
    <a href="/legacy" class="back-link">← Legacy Dashboard</a>
  </div>

  <div class="card" style="background: linear-gradient(135deg, #1a2332 0%, #151a23 100%);">
    <h3>Portfolio Overview</h3>
    <div style="display: flex; gap: 24px; flex-wrap: wrap;">
      <div>
        <div class="muted" style="font-size: 0.9em;">Total Portfolio Value</div>
        <div style="font-size: 2em; font-weight: bold; color: #25d160;" id="portfolio-total">$0.00</div>
      </div>
      <div>
        <div class="muted" style="font-size: 0.9em;">Available Cash</div>
        <div style="font-size: 2em; font-weight: bold; color: #00d4ff;" id="portfolio-cash">$0.00</div>
      </div>
      <div>
        <div class="muted" style="font-size: 0.9em;">In Positions</div>
        <div style="font-size: 2em; font-weight: bold; color: #9aa0a6;" id="portfolio-positions">$0.00</div>
      </div>
    </div>
  </div>

  <div class="row">
    <div class="col card">
      <h3>P&L Summary</h3>
      <div id="pnl-summary">
        <div>Total P&L: <span id="pnl-total" class="muted">—</span></div>
        <div>Win Rate: <span id="pnl-winrate" class="muted">—</span></div>
        <div>Avg Trade P&L: <span id="pnl-avg" class="muted">—</span></div>
        <div>Trades: <span id="pnl-count" class="muted">—</span></div>
      </div>
      <h4 style="margin-top:12px;">P&L Chart</h4>
      <canvas id="pnl-chart"></canvas>
    </div>

    <div class="col card">
      <h3>Active Trades</h3>
      <div style="max-height:400px; overflow-y:auto;">
      <table id="active-table">
        <thead><tr>
          <th>Symbol</th><th>Side</th><th>Entry</th><th>Price</th><th>Size</th><th>P&L</th><th>Entry (PHX)</th>
        </tr></thead>
        <tbody></tbody>
      </table>
      </div>
    </div>
  </div>

  <div class="card">
    <h3>Trade History</h3>
    <div style="max-height:400px; overflow-y:auto;">
    <table id="history-table">
      <thead><tr>
        <th>Symbol</th><th>Side</th><th>Entry</th><th>Exit</th><th>Size</th><th>P&L</th><th>Entry (PHX)</th><th>Exit (PHX)</th>
      </tr></thead>
      <tbody></tbody>
    </table>
    </div>
  </div>

<script>
let refreshMs = 60000;

async function fetchJSON(url) {
  const res = await fetch(url);
  return await res.json();
}

// Check environment on load
async function checkEnvironment() {
  try {
    const env = await fetchJSON('/api/environment');
    const badge = document.getElementById('env-badge');
    if (env.is_reserved_vm) {
      badge.textContent = 'RESERVED VM';
      badge.style.background = '#00ff88';
      badge.style.color = '#000';
      badge.style.fontWeight = 'bold';
    } else {
      badge.textContent = 'DEVELOPMENT';
      badge.style.background = '#ffa500';
      badge.style.color = '#000';
      badge.style.fontWeight = 'bold';
    }
  } catch (e) {
    console.log('Could not check environment:', e);
  }
}
checkEnvironment();

function colorClass(val) { return (val >= 0) ? "green" : "red"; }

function renderPNL(summary, portfolio) {
  document.getElementById("pnl-total").textContent = `$${summary.total_pnl_usd.toFixed(2)}`;
  document.getElementById("pnl-total").className = colorClass(summary.total_pnl_usd);
  document.getElementById("pnl-winrate").textContent = `${summary.win_rate_pct.toFixed(2)}%`;
  document.getElementById("pnl-avg").textContent = `$${summary.avg_trade_pnl_usd.toFixed(2)}`;
  document.getElementById("pnl-count").textContent = summary.trades_count;
  
  if (portfolio) {
    document.getElementById("portfolio-total").textContent = `$${portfolio.total_value.toFixed(2)}`;
    document.getElementById("portfolio-cash").textContent = `$${portfolio.cash.toFixed(2)}`;
    document.getElementById("portfolio-positions").textContent = `$${portfolio.positions_value.toFixed(2)}`;
  }

  const canvas = document.getElementById("pnl-chart");
  const ctx = canvas.getContext("2d");
  const data = summary.time_series.map(x => x.pnl_usd);
  const timestamps = summary.time_series.map(x => x.ts);
  
  if (data.length === 0) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "#9aa0a6"; ctx.font = "14px sans-serif";
    ctx.fillText("No data for selected timeframe", 50, canvas.height / 2);
    return;
  }

  const W = canvas.width, H = canvas.height;
  const padLeft = 60, padRight = 20, padTop = 20, padBottom = 40;
  const minV = Math.min(...data, 0), maxV = Math.max(...data, 0);
  const yScale = (H - padTop - padBottom) / ((maxV - minV) || 1);
  const xScale = (W - padLeft - padRight) / Math.max(data.length - 1, 1);
  
  ctx.clearRect(0, 0, W, H);
  
  // Draw Y-axis labels and grid lines
  ctx.fillStyle = "#9aa0a6"; ctx.font = "11px sans-serif"; ctx.textAlign = "right";
  const ySteps = 5;
  for (let i = 0; i <= ySteps; i++) {
    const val = minV + (maxV - minV) * (i / ySteps);
    const y = H - padBottom - (val - minV) * yScale;
    
    // Grid line
    ctx.strokeStyle = "#2a2a2a"; ctx.lineWidth = 1; ctx.beginPath();
    ctx.moveTo(padLeft, y); ctx.lineTo(W - padRight, y); ctx.stroke();
    
    // Label
    ctx.fillText(`$${val.toFixed(0)}`, padLeft - 5, y + 4);
  }
  
  // Draw X-axis labels (time)
  ctx.textAlign = "center"; ctx.fillStyle = "#9aa0a6";
  const xLabels = Math.min(5, data.length);
  for (let i = 0; i < xLabels; i++) {
    const idx = Math.floor(i * (data.length - 1) / Math.max(xLabels - 1, 1));
    const x = padLeft + idx * xScale;
    const date = new Date(timestamps[idx] * 1000);
    const label = date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit' });
    ctx.fillText(label, x, H - padBottom + 20);
  }
  
  // Draw P&L line
  ctx.strokeStyle = "#25d160"; ctx.lineWidth = 2; ctx.beginPath();
  data.forEach((v, i) => {
    const x = padLeft + i * xScale;
    const y = H - padBottom - (v - minV) * yScale;
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();
  
  // Draw zero line (thicker for emphasis)
  const zeroY = H - padBottom - (0 - minV) * yScale;
  ctx.strokeStyle = "#666"; ctx.lineWidth = 2; ctx.beginPath(); 
  ctx.moveTo(padLeft, zeroY); ctx.lineTo(W - padRight, zeroY); ctx.stroke();
  
  // Add axis labels
  ctx.fillStyle = "#e6e6e6"; ctx.font = "12px sans-serif";
  ctx.textAlign = "center";
  ctx.fillText("Time", W / 2, H - 5);
  
  ctx.save();
  ctx.translate(15, H / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText("P&L (USD)", 0, 0);
  ctx.restore();
}

function renderActive(rows) {
  const tbody = document.querySelector("#active-table tbody");
  tbody.innerHTML = "";
  if (rows.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#9aa0a6;">No active trades</td></tr>';
    return;
  }
  rows.forEach(r => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${r.symbol}</td>
      <td>${r.side}</td>
      <td>${r.entry_price}</td>
      <td>${r.current_price}</td>
      <td>${r.size_units.toFixed(2)}</td>
      <td class="${r.pnl_color}">$${r.pnl_usd_unrealized.toFixed(2)}</td>
      <td>${r.entry_time_phx}</td>`;
    tbody.appendChild(tr);
  });
}

function renderHistory(rows) {
  const tbody = document.querySelector("#history-table tbody");
  tbody.innerHTML = "";
  if (rows.length === 0) {
    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:#9aa0a6;">No trade history</td></tr>';
    return;
  }
  rows.forEach(r => {
    const tr = document.createElement("tr");
    const pnlClass = (r.pnl_usd_realized >= 0) ? "green" : "red";
    tr.innerHTML = `
      <td>${r.symbol}</td>
      <td>${r.side}</td>
      <td>${r.entry_price}</td>
      <td>${r.exit_price}</td>
      <td>${r.size_units.toFixed(2)}</td>
      <td class="${pnlClass}">$${r.pnl_usd_realized.toFixed(2)}</td>
      <td>${r.entry_time_phx}</td>
      <td>${r.exit_time_phx}</td>`;
    tbody.appendChild(tr);
  });
}

async function refresh() {
  try {
    const tf = document.getElementById("tf").value;
    const venue = document.getElementById("venue").value;
    
    // Build endpoint URLs based on selected venue
    let pnlEndpoint, historyEndpoint;
    if (venue === "spot") {
      pnlEndpoint = `/api/phase8/pnl/spot?tf=${tf}`;
      historyEndpoint = `/api/phase8/trades/history/spot?tf=${tf}`;
    } else if (venue === "futures") {
      pnlEndpoint = `/api/phase8/pnl/futures?tf=${tf}`;
      historyEndpoint = `/api/phase8/trades/history/futures?tf=${tf}`;
    } else {
      // "all" - combined
      pnlEndpoint = `/api/phase8/pnl?tf=${tf}`;
      historyEndpoint = `/api/phase8/trades/history?tf=${tf}`;
    }
    
    const pnl = await fetchJSON(pnlEndpoint);
    const active = await fetchJSON(`/api/phase8/trades/active`);
    const history = await fetchJSON(historyEndpoint);
    
    renderPNL(pnl.summary, pnl.portfolio || {total_value: 10000, cash: 10000, positions_value: 0});
    renderActive(active.active);
    renderHistory(history.history);
    document.getElementById("updated").textContent = `Updated: ${pnl.updated_at_phx}`;
  } catch (e) {
    console.error("Refresh error:", e);
  }
}

document.getElementById("tf").addEventListener("change", refresh);
document.getElementById("venue").addEventListener("change", refresh);
refresh();
setInterval(refresh, refreshMs);
</script>
</body>
</html>
"""
    return html


# NOTE: /api/open_positions_snapshot endpoint moved to pnl_dashboard.py to avoid duplicate registration


@app.route("/api/phase8/trades/active")
def api_phase8_trades_active():
    """API: Active trades."""
    try:
        from src.phase8_trader_dashboard import api_trades_active
        return jsonify(api_trades_active())
    except Exception as e:
        return jsonify({"active": [], "updated_at_phx": "Error", "error": str(e)})


@app.route("/api/phase8/trades/history")
def api_phase8_trades_history():
    """API: Trade history."""
    try:
        from flask import request
        from src.phase8_trader_dashboard import api_trades_history
        tf = request.args.get("tf", "1D")
        return jsonify(api_trades_history(tf))
    except Exception as e:
        return jsonify({"history": [], "timeframe": "1D", "updated_at_phx": "Error", "error": str(e)})


@app.route("/api/phase8/pnl")
def api_phase8_pnl():
    """API: P&L summary and series."""
    try:
        from flask import request
        from src.phase8_trader_dashboard import api_pnl
        tf = request.args.get("tf", "1D")
        return jsonify(api_pnl(tf))
    except Exception as e:
        return jsonify({
            "summary": {
                "timeframe": "1D",
                "total_pnl_usd": 0.0,
                "win_rate_pct": 0.0,
                "avg_trade_pnl_usd": 0.0,
                "trades_count": 0,
                "time_series": []
            },
            "updated_at_phx": "Error",
            "error": str(e)
        })


@app.route("/api/phase8/pnl/spot")
def api_phase8_pnl_spot():
    """API: Spot-only P&L summary and series."""
    try:
        from flask import request
        from src.phase8_trader_dashboard import api_pnl_spot
        tf = request.args.get("tf", "1D")
        return jsonify(api_pnl_spot(tf))
    except Exception as e:
        return jsonify({
            "summary": {
                "venue": "spot",
                "timeframe": "1D",
                "total_pnl_usd": 0.0,
                "win_rate_pct": 0.0,
                "avg_trade_pnl_usd": 0.0,
                "trades_count": 0,
                "time_series": []
            },
            "updated_at_phx": "Error",
            "error": str(e)
        })


@app.route("/api/phase8/pnl/futures")
def api_phase8_pnl_futures():
    """API: Futures-only P&L summary and series."""
    try:
        from flask import request
        from src.phase8_trader_dashboard import api_pnl_futures
        tf = request.args.get("tf", "1D")
        return jsonify(api_pnl_futures(tf))
    except Exception as e:
        return jsonify({
            "summary": {
                "venue": "futures",
                "timeframe": "1D",
                "total_pnl_usd": 0.0,
                "win_rate_pct": 0.0,
                "avg_trade_pnl_usd": 0.0,
                "trades_count": 0,
                "time_series": []
            },
            "updated_at_phx": "Error",
            "error": str(e)
        })


@app.route("/api/phase8/trades/history/spot")
def api_phase8_trades_history_spot():
    """API: Spot-only trade history."""
    try:
        from flask import request
        from src.phase8_trader_dashboard import api_trades_history_spot
        tf = request.args.get("tf", "1D")
        return jsonify(api_trades_history_spot(tf))
    except Exception as e:
        return jsonify({"history": [], "venue": "spot", "timeframe": "1D", "updated_at_phx": "Error", "error": str(e)})


@app.route("/api/phase8/trades/history/futures")
def api_phase8_trades_history_futures():
    """API: Futures-only trade history."""
    try:
        from flask import request
        from src.phase8_trader_dashboard import api_trades_history_futures
        tf = request.args.get("tf", "1D")
        return jsonify(api_trades_history_futures(tf))
    except Exception as e:
        return jsonify({"history": [], "venue": "futures", "timeframe": "1D", "updated_at_phx": "Error", "error": str(e)})


@app.route("/api/phase73/blocked-reasons")
def api_phase73_blocked_reasons():
    """API: Blocked reasons panel (Phase 7.3)."""
    try:
        from flask import request
        from src.phase73_telemetry import get_phase73_telemetry
        
        hours = int(request.args.get("hours", 24))
        telemetry = get_phase73_telemetry()
        
        symbols = ["ETHUSDT", "SOLUSDT", "AVAXUSDT", "DOTUSDT", "TRXUSDT", "BTCUSDT"]
        data = {}
        
        for symbol in symbols:
            reasons = telemetry.get_blocked_reasons_symbol(symbol, hours)
            counts = {}
            for r in reasons:
                counts[r] = counts.get(r, 0) + 1
            top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:5]
            data[symbol] = [{"reason": r, "count": c} for r, c in top]
        
        return jsonify({
            "window_hours": hours,
            "data": data,
            "updated_at": datetime.now(ARIZONA_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
        })
    except Exception as e:
        return jsonify({"error": str(e), "data": {}})


@app.route("/api/phase73/fees-summary")
def api_phase73_fees_summary():
    """API: Fees summary panel (Phase 7.3)."""
    try:
        from flask import request
        from src.phase73_telemetry import get_phase73_telemetry
        
        hours = int(request.args.get("hours", 24))
        telemetry = get_phase73_telemetry()
        
        symbols = ["ETHUSDT", "SOLUSDT", "AVAXUSDT", "DOTUSDT", "TRXUSDT", "BTCUSDT"]
        total_maker = 0.0
        total_taker = 0.0
        per_symbol = {}
        
        for symbol in symbols:
            maker, taker = telemetry.get_fees_symbol(symbol, hours)
            total_maker += maker
            total_taker += taker
            per_symbol[symbol] = {"maker_usd": round(maker, 2), "taker_usd": round(taker, 2)}
        
        return jsonify({
            "window_hours": hours,
            "total_maker_usd": round(total_maker, 2),
            "total_taker_usd": round(total_taker, 2),
            "per_symbol": per_symbol,
            "updated_at": datetime.now(ARIZONA_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
        })
    except Exception as e:
        return jsonify({"error": str(e), "per_symbol": {}})


@app.route("/api/phase73/controller-status")
def api_phase73_controller_status():
    """API: Controller status (Phase 7.3)."""
    try:
        from src.phase73_controller import get_phase73_controller
        
        controller = get_phase73_controller()
        status = controller.get_status()
        
        return jsonify({
            "relax_pct_stable": status["relax_pct_stable"],
            "min_hold_symbol": status["min_hold_symbol"],
            "last_run": datetime.fromtimestamp(status["last_controller_run"], ARIZONA_TZ).strftime("%Y-%m-%d %H:%M:%S %Z") if status["last_controller_run"] > 0 else "Never",
            "next_run_in_sec": int(status["next_run_in_sec"]),
            "updated_at": datetime.now(ARIZONA_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
        })
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/export-codebase")
def export_codebase_endpoint():
    """Export complete trading bot codebase as downloadable JSON."""
    try:
        from src.export_codebase import export_complete_codebase
        from flask import Response
        import datetime
        
        export_data = export_complete_codebase()
        json_data = json.dumps(export_data, indent=2, ensure_ascii=False)
        
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"trading_bot_complete_export_{timestamp}.json"
        
        return Response(
            json_data,
            mimetype="application/json",
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )
        
    except Exception as e:
        import traceback
        return f"<pre>Codebase Export Error: {str(e)}\n\n{traceback.format_exc()}</pre>", 500


@app.route("/health")
def health_check_page():
    """Health check dashboard page."""
    try:
        from src.health_check import run_health_check
        results = run_health_check()
        
        # Color mapping
        status_colors = {
            "healthy": "#00ff88",
            "healthy_with_warnings": "#ffa500",
            "unhealthy": "#ff4466",
            "unknown": "#888"
        }
        
        status_color = status_colors.get(results["status"], "#888")
        
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Health Check - Trading Bot</title>
    <meta http-equiv="refresh" content="60">
    <style>
        body {{ font-family: monospace; background: #0a0a0a; color: #e0e0e0; padding: 20px; }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        .header {{ border-bottom: 2px solid #00ff00; padding-bottom: 10px; margin-bottom: 20px; }}
        .nav {{ margin-bottom: 20px; }}
        .nav a {{ color: #00ff00; text-decoration: none; padding: 10px 20px; background: #1a1a1a; border-radius: 5px; margin-right: 10px; }}
        .nav a:hover {{ background: #2a2a2a; }}
        .status-card {{ background: #1a1a1a; border: 2px solid {status_color}; padding: 20px; border-radius: 10px; margin-bottom: 20px; }}
        .status-title {{ font-size: 2em; color: {status_color}; }}
        .metric-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; margin-bottom: 20px; }}
        .metric-box {{ background: #1a1a1a; border: 1px solid #333; padding: 15px; border-radius: 5px; }}
        .metric-label {{ color: #888; font-size: 0.9em; }}
        .metric-value {{ font-size: 1.5em; font-weight: bold; }}
        .pass {{ color: #00ff88; }}
        .fail {{ color: #ff4466; }}
        .warn {{ color: #ffa500; }}
        .section {{ background: #1a1a1a; border: 1px solid #333; padding: 20px; border-radius: 5px; margin-bottom: 20px; }}
        .section h3 {{ color: #00ff00; margin-top: 0; }}
        .error-list {{ list-style: none; padding: 0; }}
        .error-item {{ padding: 10px; margin: 5px 0; background: #2a1a1a; border-left: 3px solid #ff4466; }}
        .warning-item {{ padding: 10px; margin: 5px 0; background: #2a2a1a; border-left: 3px solid #ffa500; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #333; }}
        th {{ color: #00ff00; }}
        .status-ok {{ color: #00ff88; }}
        .status-failed {{ color: #ff4466; }}
        .status-warning {{ color: #ffa500; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🏥 Bot Health Check</h1>
        </div>
        
        <div class="nav">
            <a href="/">← Main Dashboard</a>
            <a href="/elite">Elite Diagnostics</a>
            <a href="/phase2">Phase 2</a>
            <a href="/phase3">Phase 3</a>
        </div>
        
        <div class="status-card">
            <div class="status-title">Status: {results['status'].upper().replace('_', ' ')}</div>
            <p style="color: #888; margin-top: 10px;">Last checked: {get_arizona_time().strftime("%Y-%m-%d %H:%M:%S %Z")}</p>
        </div>
        
        <div class="metric-grid">
            <div class="metric-box">
                <div class="metric-label">Checks Passed</div>
                <div class="metric-value pass">✅ {results['checks_passed']}</div>
            </div>
            <div class="metric-box">
                <div class="metric-label">Checks Failed</div>
                <div class="metric-value fail">❌ {results['checks_failed']}</div>
            </div>
            <div class="metric-box">
                <div class="metric-label">Warnings</div>
                <div class="metric-value warn">⚠️ {results['warnings']}</div>
            </div>
        </div>
        
        {f'''
        <div class="section">
            <h3>❌ Errors ({len(results["errors"])})</h3>
            <ul class="error-list">
                {''.join(f'<li class="error-item">{error}</li>' for error in results["errors"])}
            </ul>
        </div>
        ''' if results["errors"] else ''}
        
        {f'''
        <div class="section">
            <h3>⚠️ Warnings ({len(results["warnings_list"])})</h3>
            <ul class="error-list">
                {''.join(f'<li class="warning-item">{warning}</li>' for warning in results["warnings_list"])}
            </ul>
        </div>
        ''' if results["warnings_list"] else ''}
        
        <div class="section">
            <h3>📦 Module Imports</h3>
            <table>
                <tr><th>Module</th><th>Status</th></tr>
                {''.join(f'<tr><td>{item["module"]}</td><td class="status-{item["status"]}">{item["status"].upper()}</td></tr>' for item in results["details"].get("imports", []))}
            </table>
        </div>
        
        <div class="section">
            <h3>⚙️ Configuration Files</h3>
            <table>
                <tr><th>File</th><th>Status</th></tr>
                {''.join(f'<tr><td>{item["file"]}</td><td class="status-{item["status"]}">{item["status"].upper()}</td></tr>' for item in results["details"].get("config_files", []))}
            </table>
        </div>
        
        <div class="section">
            <h3>📊 System Components</h3>
            <table>
                <tr><th>Component</th><th>Status</th><th>Details</th></tr>
                <tr>
                    <td>Daily Stats</td>
                    <td class="status-{results['details'].get('daily_stats', {}).get('status', 'unknown')}">{results['details'].get('daily_stats', {}).get('status', 'unknown').upper()}</td>
                    <td>{results['details'].get('daily_stats', {}).get('current_date', 'N/A')} | {results['details'].get('daily_stats', {}).get('trades_today', 0)} trades today</td>
                </tr>
                <tr>
                    <td>Phase 2</td>
                    <td class="status-{results['details'].get('phase2', {}).get('status', 'unknown')}">{results['details'].get('phase2', {}).get('status', 'unknown').upper()}</td>
                    <td>Shadow: {results['details'].get('phase2', {}).get('shadow_mode', 'N/A')} | Kill Switch: {results['details'].get('phase2', {}).get('kill_switch', 'N/A')}</td>
                </tr>
                <tr>
                    <td>Phase 3</td>
                    <td class="status-{results['details'].get('phase3', {}).get('status', 'unknown')}">{results['details'].get('phase3', {}).get('status', 'unknown').upper()}</td>
                    <td>Ramp Stage: {results['details'].get('phase3', {}).get('ramp_stage', 'N/A')} | Leverage: {results['details'].get('phase3', {}).get('leverage_cap', 'N/A')}x</td>
                </tr>
            </table>
        </div>
        
        <div class="section">
            <h3>💾 Portfolio Trackers</h3>
            <table>
                <tr><th>Tracker</th><th>Status</th><th>Has Data</th></tr>
                {''.join(f'<tr><td>{item["tracker"]}</td><td class="status-{item["status"]}">{item["status"].upper()}</td><td>{item.get("has_data", "N/A")}</td></tr>' for item in results["details"].get("portfolio_trackers", []))}
            </table>
        </div>
        
        <p style="text-align: center; color: #666; margin-top: 30px;">
            Auto-refresh every 60s | Run manual check: <code>python3 src/health_check.py</code>
        </p>
    </div>
</body>
</html>
        """
        
        return html
        
    except Exception as e:
        return f"<html><body><h1>Error running health check</h1><p>{str(e)}</p></body></html>"


@app.route("/api/health")
def health_check_api():
    """API endpoint for health check."""
    try:
        from src.health_check import run_health_check
        results = run_health_check()
        return jsonify(results)
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


@app.route("/api/bot-comparison")
def bot_comparison_api():
    """API endpoint for Alpha vs Beta bot comparison."""
    try:
        from src.bot_registry import compare_bots
        comparison = compare_bots()
        return jsonify(comparison)
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


@app.route("/api/time-filter-scenarios")
def time_filter_scenarios_api():
    """API endpoint for time filter scenario analysis."""
    try:
        from src.signal_universe_tracker import get_time_filter_dashboard_data
        data = get_time_filter_dashboard_data()
        return jsonify(data)
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


@app.route("/time-scenarios")
def time_scenarios_dashboard():
    """Dashboard page for time filter scenario analysis."""
    try:
        from src.signal_universe_tracker import get_time_filter_dashboard_data, analyze_time_filter_scenarios
        
        data = get_time_filter_dashboard_data()
        analysis = analyze_time_filter_scenarios(days=7)
        
        scenarios_html = ""
        for s in data.get("scenarios", []):
            bg = "#1a3a1a" if s.get("is_current") else "#1a1a1a"
            border = "#00ff88" if s.get("is_current") else "#333"
            label = " (CURRENT)" if s.get("is_current") else ""
            pnl_class = "profit" if "+" in s.get("theoretical_pnl", "") else "loss"
            scenarios_html += f'''
            <div class="scenario-card" style="background: {bg}; border-color: {border};">
                <div class="scenario-name">{s['name']}{label}</div>
                <div class="scenario-stats">
                    <div class="stat">
                        <span class="label">Would Allow</span>
                        <span class="value">{s['would_allow']}</span>
                    </div>
                    <div class="stat">
                        <span class="label">Would Block</span>
                        <span class="value">{s['would_block']}</span>
                    </div>
                    <div class="stat">
                        <span class="label">Win Rate</span>
                        <span class="value">{s['theoretical_win_rate']}</span>
                    </div>
                    <div class="stat">
                        <span class="label">P&L</span>
                        <span class="value {pnl_class}">{s['theoretical_pnl']}</span>
                    </div>
                </div>
            </div>
            '''
        
        best = data.get("best_scenario", {})
        recommendation = data.get("recommendation", "Collecting data...")
        
        html = f'''<!DOCTYPE html>
<html>
<head>
    <title>Time Filter Scenarios</title>
    <meta http-equiv="refresh" content="60">
    <style>
        body {{ font-family: monospace; background: #0a0a0a; color: #e0e0e0; padding: 20px; margin: 0; }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        .header {{ border-bottom: 2px solid #00ff00; padding-bottom: 10px; margin-bottom: 20px; }}
        .nav {{ margin-bottom: 20px; }}
        .nav a {{ color: #00ff00; text-decoration: none; padding: 10px 20px; background: #1a1a1a; border-radius: 5px; margin-right: 10px; display: inline-block; }}
        .nav a:hover {{ background: #2a2a2a; }}
        .summary {{ background: #1a1a1a; border: 1px solid #333; padding: 20px; border-radius: 10px; margin-bottom: 20px; }}
        .summary-title {{ color: #00ff00; font-size: 1.2em; margin-bottom: 15px; }}
        .scenarios-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 15px; margin-bottom: 20px; }}
        .scenario-card {{ border: 2px solid #333; padding: 15px; border-radius: 8px; }}
        .scenario-name {{ font-size: 1.1em; color: #fff; margin-bottom: 10px; font-weight: bold; }}
        .scenario-stats {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }}
        .stat {{ background: #0a0a0a; padding: 8px; border-radius: 4px; }}
        .stat .label {{ font-size: 0.8em; color: #888; display: block; }}
        .stat .value {{ font-size: 1.1em; font-weight: bold; }}
        .profit {{ color: #00ff88; }}
        .loss {{ color: #ff4466; }}
        .recommendation {{ background: #1a2a1a; border: 2px solid #00ff88; padding: 20px; border-radius: 10px; }}
        .recommendation-title {{ color: #00ff88; font-size: 1.1em; margin-bottom: 10px; }}
        .best-scenario {{ background: #2a2a1a; padding: 15px; border-radius: 8px; margin-bottom: 15px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Time Filter Scenario Analysis</h1>
            <p>Counterfactual analysis: What if we used different time filters?</p>
        </div>
        
        <div class="nav">
            <a href="/">Main Dashboard</a>
            <a href="/bots">Bot Comparison</a>
            <a href="/futures">Futures</a>
            <a href="/health">Health Check</a>
        </div>
        
        <div class="summary">
            <div class="summary-title">Current Configuration</div>
            <p>Filter: <strong>{data.get('current_filter', 'N/A')}</strong></p>
            <p>Signals blocked (7d): <strong>{data.get('signals_blocked_7d', 0)}</strong></p>
        </div>
        
        <div class="best-scenario">
            <div class="summary-title">Best Performing Scenario</div>
            <p>Scenario: <strong>{best.get('name', 'N/A')}</strong></p>
            <p>Theoretical P&L: <strong class="profit">{best.get('theoretical_pnl_pct', 0):+.2f}%</strong></p>
            <p>Win Rate: <strong>{best.get('theoretical_win_rate', 0):.1f}%</strong></p>
        </div>
        
        <div class="recommendation">
            <div class="recommendation-title">Recommendation</div>
            <p>{recommendation}</p>
        </div>
        
        <h2 style="color: #00ff00; margin: 30px 0 15px;">Scenario Comparison</h2>
        <div class="scenarios-grid">
            {scenarios_html}
        </div>
        
        <p style="color: #666; font-size: 0.9em; margin-top: 30px;">
            Note: Theoretical P&L is based on counterfactual analysis of blocked signals.
            As more signals are blocked and tracked, these projections will become more accurate.
        </p>
    </div>
</body>
</html>'''
        
        return html
        
    except Exception as e:
        import traceback
        return f"<pre>Error: {e}\n{traceback.format_exc()}</pre>", 500


@app.route("/api/strategic-advisor")
def strategic_advisor_api():
    """API endpoint for Strategic Advisor insights."""
    try:
        from src.strategic_advisor import StrategicAdvisor
        advisor = StrategicAdvisor()
        insights = advisor.get_latest_insights()
        return jsonify(insights)
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/strategic-advisor")
def strategic_advisor_dashboard():
    """Dashboard page for Strategic Advisor - proactive profitability insights."""
    try:
        from src.strategic_advisor import StrategicAdvisor
        advisor = StrategicAdvisor()
        insights = advisor.get_latest_insights()
        
        recommendations = insights.get('top_recommendations', [])
        metrics = insights.get('metrics', {})
        fee_analysis = insights.get('fee_analysis', {})
        exit_analysis = insights.get('exit_analysis', {})
        last_analysis = insights.get('last_run', 'Never')
        
        rec_html = ""
        for rec in recommendations[:10]:
            priority = rec.get('priority', 'low').upper()
            priority_color = '#ff4466' if priority == 'HIGH' else '#ffaa00' if priority == 'MEDIUM' else '#888'
            rec_html += f'''
            <div class="recommendation-item" style="border-left: 4px solid {priority_color}; padding: 15px; margin-bottom: 15px; background: #1a1a1a; border-radius: 5px;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <span style="color: {priority_color}; font-weight: bold;">[{priority}]</span>
                    <span style="color: #666; font-size: 0.8em;">{rec.get('type', 'General')}</span>
                </div>
                <p style="margin: 10px 0; color: #e0e0e0;">{rec.get('issue', 'No issue')}</p>
                <p style="margin: 5px 0; color: #00ff88; font-size: 0.9em;">Action: {rec.get('action', 'N/A')}</p>
                <p style="margin: 5px 0; color: #888; font-size: 0.8em;">Impact: {rec.get('expected_impact', 'N/A')}</p>
            </div>
            '''
        
        if not rec_html:
            rec_html = '<p style="color: #666;">No recommendations available yet. Run hourly analysis to generate insights.</p>'
        
        win_rate = metrics.get('win_rate', 0)
        total_pnl = metrics.get('total_pnl', 0)
        avg_pnl = metrics.get('avg_pnl', 0)
        fee_erosion = metrics.get('fee_impact_pct', 0)
        trades_analyzed_total = exit_analysis.get('trades_analyzed', metrics.get('total_trades', 0))
        early_exits = exit_analysis.get('early_exits', 0)
        early_exit_rate = (early_exits / trades_analyzed_total * 100) if trades_analyzed_total > 0 else 0
        
        pnl_class = 'profit' if total_pnl > 0 else 'loss'
        
        html = f'''<!DOCTYPE html>
<html>
<head>
    <title>Strategic Advisor</title>
    <meta http-equiv="refresh" content="60">
    <style>
        body {{ font-family: monospace; background: #0a0a0a; color: #e0e0e0; padding: 20px; margin: 0; }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        .header {{ border-bottom: 2px solid #00ffaa; padding-bottom: 10px; margin-bottom: 20px; }}
        .nav {{ margin-bottom: 20px; }}
        .nav a {{ color: #00ff00; text-decoration: none; padding: 10px 20px; background: #1a1a1a; border-radius: 5px; margin-right: 10px; display: inline-block; }}
        .nav a:hover {{ background: #2a2a2a; }}
        .metrics-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 30px; }}
        .metric-card {{ background: #1a1a1a; border: 1px solid #333; padding: 20px; border-radius: 10px; text-align: center; }}
        .metric-value {{ font-size: 2em; font-weight: bold; color: #00ff88; }}
        .metric-value.loss {{ color: #ff4466; }}
        .metric-label {{ color: #888; font-size: 0.9em; margin-top: 5px; }}
        .section {{ background: #111; border: 1px solid #333; padding: 20px; border-radius: 10px; margin-bottom: 20px; }}
        .section-title {{ color: #00ffaa; font-size: 1.3em; margin-bottom: 15px; border-bottom: 1px solid #333; padding-bottom: 10px; }}
        .profit {{ color: #00ff88; }}
        .loss {{ color: #ff4466; }}
        .timestamp {{ color: #666; font-size: 0.9em; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Strategic Advisor</h1>
            <p>Proactive profitability intelligence - surfacing what you don't know to ask</p>
            <p class="timestamp">Last Analysis: {last_analysis}</p>
        </div>
        
        <div class="nav">
            <a href="/">Main Dashboard</a>
            <a href="/bots">Bot Comparison</a>
            <a href="/time-scenarios">Time Scenarios</a>
            <a href="/health">Health Check</a>
            <a href="/futures">Futures</a>
        </div>
        
        <h2 style="color: #00ffaa; margin-bottom: 15px;">Key Metrics (24h)</h2>
        <div class="metrics-grid">
            <div class="metric-card">
                <div class="metric-value">{win_rate:.1f}%</div>
                <div class="metric-label">Win Rate</div>
            </div>
            <div class="metric-card">
                <div class="metric-value {pnl_class}">${total_pnl:.2f}</div>
                <div class="metric-label">Total P&L</div>
            </div>
            <div class="metric-card">
                <div class="metric-value {pnl_class}">${avg_pnl:.2f}</div>
                <div class="metric-label">Avg P&L per Trade</div>
            </div>
            <div class="metric-card">
                <div class="metric-value loss">{fee_erosion:.1f}%</div>
                <div class="metric-label">Fee Erosion</div>
            </div>
            <div class="metric-card">
                <div class="metric-value loss">{early_exit_rate:.1f}%</div>
                <div class="metric-label">Early Exit Rate</div>
            </div>
            <div class="metric-card">
                <div class="metric-value">{metrics.get('total_trades', 0)}</div>
                <div class="metric-label">Trades Analyzed</div>
            </div>
        </div>
        
        <div class="section">
            <div class="section-title">Prioritized Recommendations</div>
            {rec_html}
        </div>
        
        <p style="color: #666; font-size: 0.9em; margin-top: 30px;">
            Strategic Advisor runs hourly analysis and surfaces profitability gaps, hidden risks, and optimization opportunities.
            Recommendations are prioritized by potential impact on profitability.
        </p>
    </div>
</body>
</html>'''
        
        return html
        
    except Exception as e:
        import traceback
        return f"<pre>Error: {e}\n{traceback.format_exc()}</pre>", 500


@app.route("/bots")
def bots_dashboard():
    """Dashboard page comparing Alpha and Beta trading bots."""
    try:
        from src.bot_registry import compare_bots, BotRegistry, get_tracking_config
        
        fresh_mode = request.args.get('fresh', 'true').lower() == 'true'
        
        comparison = compare_bots(fresh_only=fresh_mode)
        all_time = compare_bots(fresh_only=False)
        
        alpha = comparison.get('alpha', {})
        beta = comparison.get('beta', {})
        comp = comparison.get('comparison', {})
        leader = comp.get('leader', 'tie')
        tracking_start = comparison.get('tracking_start', 'N/A')
        
        alpha_all = all_time.get('alpha', {})
        beta_all = all_time.get('beta', {})
        
        alpha_reg = BotRegistry("alpha")
        beta_reg = BotRegistry("beta")
        
        alpha_trades = alpha_reg.get_trades(last_n=10)
        beta_trades = beta_reg.get_trades(last_n=10)
        
        def format_trade_row(t, bot_id):
            symbol = t.get('symbol', 'N/A')
            direction = t.get('direction', 'N/A')
            pnl = t.get('pnl', t.get('realized_pnl', 0))
            inverted = t.get('inverted', False)
            tier = t.get('tier', 'N/A')
            pnl_class = 'profit' if pnl > 0 else 'loss' if pnl < 0 else ''
            inv_badge = '<span class="inverted-badge">INV</span>' if inverted else ''
            return f'<tr><td>{symbol}</td><td>{direction} {inv_badge}</td><td>{tier}</td><td class="{pnl_class}">${pnl:.2f}</td></tr>'
        
        alpha_rows = ''.join([format_trade_row(t, 'alpha') for t in alpha_trades[-10:][::-1]])
        beta_rows = ''.join([format_trade_row(t, 'beta') for t in beta_trades[-10:][::-1]])
        
        alpha_border = '#00ff88' if leader == 'alpha' else '#333'
        beta_border = '#00ff88' if leader == 'beta' else '#333'
        
        fresh_btn_style = "background: #00ff88; color: #000;" if fresh_mode else "background: #1a1a1a;"
        all_btn_style = "background: #1a1a1a;" if fresh_mode else "background: #00ff88; color: #000;"
        mode_label = "FRESH START" if fresh_mode else "ALL TIME"
        
        html = f'''<!DOCTYPE html>
<html>
<head>
    <title>Bot Comparison - Alpha vs Beta</title>
    <meta http-equiv="refresh" content="30">
    <style>
        body {{ font-family: monospace; background: #0a0a0a; color: #e0e0e0; padding: 20px; margin: 0; }}
        .container {{ max-width: 1600px; margin: 0 auto; }}
        .header {{ border-bottom: 2px solid #00ff00; padding-bottom: 10px; margin-bottom: 20px; }}
        .nav {{ margin-bottom: 20px; }}
        .nav a {{ color: #00ff00; text-decoration: none; padding: 10px 20px; background: #1a1a1a; border-radius: 5px; margin-right: 10px; display: inline-block; }}
        .nav a:hover {{ background: #2a2a2a; }}
        .toggle-section {{ margin-bottom: 20px; padding: 15px; background: #1a1a1a; border-radius: 10px; border: 1px solid #333; }}
        .toggle-btn {{ padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; font-family: monospace; margin-right: 10px; }}
        .toggle-btn:hover {{ opacity: 0.9; }}
        .mode-indicator {{ background: #00ff88; color: #000; padding: 5px 10px; border-radius: 4px; font-weight: bold; }}
        .tracking-info {{ color: #888; font-size: 0.9em; margin-top: 10px; }}
        .all-time-summary {{ background: #0a0a0a; padding: 10px; border-radius: 5px; margin-top: 10px; font-size: 0.9em; color: #666; }}
        .bot-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }}
        .bot-card {{ background: #1a1a1a; border: 3px solid; padding: 20px; border-radius: 10px; }}
        .alpha-card {{ border-color: {alpha_border}; }}
        .beta-card {{ border-color: {beta_border}; }}
        .bot-title {{ font-size: 1.5em; margin-bottom: 15px; }}
        .alpha-title {{ color: #4488ff; }}
        .beta-title {{ color: #ff8844; }}
        .metrics-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; margin-bottom: 15px; }}
        .metric {{ background: #0a0a0a; padding: 10px; border-radius: 5px; text-align: center; }}
        .metric-label {{ font-size: 0.8em; color: #888; }}
        .metric-value {{ font-size: 1.3em; font-weight: bold; }}
        .profit {{ color: #00ff88; }}
        .loss {{ color: #ff4466; }}
        .leader-badge {{ background: #00ff88; color: #000; padding: 2px 8px; border-radius: 3px; font-size: 0.8em; margin-left: 10px; }}
        .strategy-badge {{ background: #333; color: #fff; padding: 2px 8px; border-radius: 3px; font-size: 0.8em; }}
        .inverted-badge {{ background: #ff8844; color: #000; padding: 1px 4px; border-radius: 2px; font-size: 0.7em; margin-left: 5px; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
        th, td {{ padding: 8px; text-align: left; border-bottom: 1px solid #333; }}
        th {{ color: #888; font-size: 0.9em; }}
        .comparison-section {{ background: #1a1a1a; border: 1px solid #333; padding: 20px; border-radius: 10px; margin-bottom: 20px; }}
        .comparison-title {{ color: #00ff00; font-size: 1.2em; margin-bottom: 15px; }}
        .delta {{ font-size: 0.9em; color: #888; }}
        .delta.positive {{ color: #00ff88; }}
        .delta.negative {{ color: #ff4466; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🤖 Alpha vs Beta Bot Comparison <span class="mode-indicator">{mode_label}</span></h1>
            <p>Real-time performance tracking of parallel trading strategies</p>
        </div>
        
        <div class="toggle-section">
            <a href="/bots?fresh=true" class="toggle-btn" style="{fresh_btn_style}">🆕 Fresh Start</a>
            <a href="/bots?fresh=false" class="toggle-btn" style="{all_btn_style}">📊 All Time</a>
            <div class="tracking-info">
                {'<strong>Tracking since:</strong> ' + tracking_start if fresh_mode else 'Showing all historical trades'}
                <br>Starting capital: $10,000 per bot
            </div>
            <div class="all-time-summary">
                <strong>Historical Reference:</strong> Alpha ({alpha_all.get('total_trades', 0):,} trades, ${alpha_all.get('realized_pnl', 0):+,.2f}) | 
                Beta ({beta_all.get('total_trades', 0):,} trades, ${beta_all.get('realized_pnl', 0):+,.2f})
            </div>
        </div>
        
        <div class="nav">
            <a href="/">← Main Dashboard</a>
            <a href="/futures">Futures</a>
            <a href="/health">Health Check</a>
        </div>
        
        <div class="comparison-section">
            <div class="comparison-title">📊 Performance Summary</div>
            <div class="metrics-grid" style="grid-template-columns: repeat(4, 1fr);">
                <div class="metric">
                    <div class="metric-label">Leader</div>
                    <div class="metric-value" style="color: {'#4488ff' if leader == 'alpha' else '#ff8844'};">{leader.upper()}</div>
                </div>
                <div class="metric">
                    <div class="metric-label">P&L Delta</div>
                    <div class="metric-value {'profit' if comp.get('pnl_delta', 0) > 0 else 'loss'}">${comp.get('pnl_delta', 0):+,.2f}</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Win Rate Delta</div>
                    <div class="metric-value {'profit' if comp.get('win_rate_delta', 0) > 0 else 'loss'}">{comp.get('win_rate_delta', 0):+.1f}%</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Trade Count Delta</div>
                    <div class="metric-value">{comp.get('trade_count_delta', 0):+d}</div>
                </div>
            </div>
        </div>
        
        <div class="bot-grid">
            <div class="bot-card alpha-card">
                <div class="bot-title alpha-title">
                    ALPHA BOT {'<span class="leader-badge">LEADER</span>' if leader == 'alpha' else ''}
                    <span class="strategy-badge">Baseline</span>
                </div>
                <div class="metrics-grid">
                    <div class="metric">
                        <div class="metric-label">Total Trades</div>
                        <div class="metric-value">{alpha.get('total_trades', 0):,}</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Win Rate</div>
                        <div class="metric-value {'profit' if alpha.get('win_rate', 0) >= 50 else ''}">{alpha.get('win_rate', 0):.1f}%</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Realized P&L</div>
                        <div class="metric-value {'profit' if alpha.get('realized_pnl', 0) > 0 else 'loss'}">${alpha.get('realized_pnl', 0):,.2f}</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Portfolio Value</div>
                        <div class="metric-value">${alpha.get('current_value', 10000):,.2f}</div>
                    </div>
                </div>
                <h4>Recent Trades</h4>
                <table>
                    <tr><th>Symbol</th><th>Direction</th><th>Tier</th><th>P&L</th></tr>
                    {alpha_rows if alpha_rows else '<tr><td colspan="4" style="text-align:center;color:#666;">No trades yet</td></tr>'}
                </table>
            </div>
            
            <div class="bot-card beta-card">
                <div class="bot-title beta-title">
                    BETA BOT {'<span class="leader-badge">LEADER</span>' if leader == 'beta' else ''}
                    <span class="strategy-badge">Signal Inversion</span>
                </div>
                <div class="metrics-grid">
                    <div class="metric">
                        <div class="metric-label">Total Trades</div>
                        <div class="metric-value">{beta.get('total_trades', 0):,}</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Win Rate</div>
                        <div class="metric-value {'profit' if beta.get('win_rate', 0) >= 50 else ''}">{beta.get('win_rate', 0):.1f}%</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Realized P&L</div>
                        <div class="metric-value {'profit' if beta.get('realized_pnl', 0) > 0 else 'loss'}">${beta.get('realized_pnl', 0):,.2f}</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Portfolio Value</div>
                        <div class="metric-value">${beta.get('current_value', 10000):,.2f}</div>
                    </div>
                </div>
                <h4>Recent Trades</h4>
                <table>
                    <tr><th>Symbol</th><th>Direction</th><th>Tier</th><th>P&L</th></tr>
                    {beta_rows if beta_rows else '<tr><td colspan="4" style="text-align:center;color:#666;">No trades yet</td></tr>'}
                </table>
            </div>
        </div>
        
        <div class="comparison-section">
            <div class="comparison-title">📝 Strategy Details</div>
            <table>
                <tr><th>Aspect</th><th>Alpha (Baseline)</th><th>Beta (Inversion)</th></tr>
                <tr><td>Strategy</td><td>Current trading logic with all learning systems</td><td>Inverts F-tier signals, respects direction biases</td></tr>
                <tr><td>Signal Processing</td><td>Execute signals as generated</td><td>LONG↔SHORT for low-confidence (F-tier) signals</td></tr>
                <tr><td>Sizing</td><td>Win-rate based scaling</td><td>Tier-based multipliers (A=1.5x, F=0.5x)</td></tr>
                <tr><td>Learning</td><td>Nightly learning orchestrator</td><td>Parallel learning with inversion feedback</td></tr>
            </table>
        </div>
        
        <p style="text-align: center; color: #666; margin-top: 30px;">
            Auto-refresh every 30s | Last updated: {datetime.now(ARIZONA_TZ).strftime("%Y-%m-%d %H:%M:%S")} AZ
        </p>
    </div>
</body>
</html>'''
        
        return html
        
    except Exception as e:
        import traceback
        return f'''<html><body style="background:#0a0a0a;color:#fff;font-family:monospace;padding:20px;">
            <h1>Bot Comparison Error</h1>
            <p style="color:#ff4466;">{str(e)}</p>
            <pre>{traceback.format_exc()}</pre>
            <a href="/" style="color:#00ff00;">← Back to Main Dashboard</a>
        </body></html>'''


@app.route("/phase4")
def phase4_dashboard():
    """Phase 4 Watchdog dashboard page."""
    try:
        from src.phase4_watchdog import get_watchdog
        watchdog = get_watchdog()
        status = watchdog.get_status()
        
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Phase 4 Watchdog - Trading Bot</title>
    <meta http-equiv="refresh" content="30">
    <style>
        body {{ font-family: monospace; background: #0a0a0a; color: #e0e0e0; padding: 20px; }}
        .container {{ max-width: 1600px; margin: 0 auto; }}
        .header {{ border-bottom: 2px solid #00ff00; padding-bottom: 10px; margin-bottom: 20px; }}
        .nav {{ margin-bottom: 20px; }}
        .nav a {{ color: #00ff00; text-decoration: none; padding: 10px 20px; background: #1a1a1a; border-radius: 5px; margin-right: 10px; }}
        .nav a:hover {{ background: #2a2a2a; }}
        .status-card {{ background: #1a1a1a; border: 2px solid {'#00ff88' if not status['degraded'] else '#ff4466'}; padding: 20px; border-radius: 10px; margin-bottom: 20px; }}
        .status-title {{ font-size: 2em; color: {'#00ff88' if not status['degraded'] else '#ff4466'}; }}
        .metric-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 15px; margin-bottom: 20px; }}
        .metric-box {{ background: #1a1a1a; border: 1px solid #333; padding: 15px; border-radius: 5px; }}
        .metric-label {{ color: #888; font-size: 0.9em; }}
        .metric-value {{ font-size: 1.5em; font-weight: bold; }}
        .ok {{ color: #00ff88; }}
        .degraded {{ color: #ff4466; }}
        .section {{ background: #1a1a1a; border: 1px solid #333; padding: 20px; border-radius: 5px; margin-bottom: 20px; }}
        .section h3 {{ color: #00ff00; margin-top: 0; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #333; }}
        th {{ color: #00ff00; }}
        .event-log {{ max-height: 400px; overflow-y: auto; font-size: 0.9em; }}
        .event-item {{ padding: 8px; margin: 4px 0; background: #1a1a1a; border-left: 3px solid #00ff88; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🔍 Phase 4 Watchdog</h1>
        </div>
        
        <div class="nav">
            <a href="/">← Main Dashboard</a>
            <a href="/phase2">Phase 2</a>
            <a href="/phase3">Phase 3</a>
            <a href="/health">Health Check</a>
        </div>
        
        <div class="status-card">
            <div class="status-title">Status: {'HEALTHY' if not status['degraded'] else 'DEGRADED'}</div>
            <p style="color: #888; margin-top: 10px;">
                {f'System degraded for {status["degraded_duration_min"]:.1f} minutes' if status['degraded'] else 'All systems operational'}
            </p>
        </div>
        
        <div class="metric-grid">
            <div class="metric-box">
                <div class="metric-label">Watchdog Status</div>
                <div class="metric-value {'ok' if status['running'] else 'degraded'}">
                    {'🟢 RUNNING' if status['running'] else '🔴 STOPPED'}
                </div>
            </div>
            <div class="metric-box">
                <div class="metric-label">Synthetic Tests</div>
                <div class="metric-value ok">{status['synthetic_tests']}</div>
            </div>
            <div class="metric-box">
                <div class="metric-label">Golden Signals Samples</div>
                <div class="metric-value ok">{status['golden_signals_samples']}</div>
            </div>
        </div>
        
        <div class="section">
            <h3>💓 Module Heartbeats</h3>
            <table>
                <tr><th>Module</th><th>Status</th><th>Missed</th><th>Last Seen</th></tr>
                {''.join(f'<tr><td>{name}</td><td class="{hb["status"]}">{hb["status"].upper()}</td><td>{hb["missed"]}</td><td>{datetime.fromtimestamp(hb["last_seen"]).strftime("%H:%M:%S") if hb["last_seen"] else "Never"}</td></tr>' for name, hb in status['heartbeats'].items())}
            </table>
        </div>
        
        <div class="section">
            <h3>🔌 Integration Health</h3>
            <table>
                <tr><th>Integration</th><th>Status</th><th>Circuit</th><th>Failures</th><th>Last OK</th></tr>
                {''.join(f'<tr><td>{name}</td><td class="{integ["status"]}">{integ["status"].upper()}</td><td>{"🔴 OPEN" if integ["circuit_open"] else "🟢 CLOSED"}</td><td>{integ["consecutive_failures"]}</td><td>{datetime.fromtimestamp(integ["last_ok"]).strftime("%H:%M:%S") if integ["last_ok"] else "Never"}</td></tr>' for name, integ in status['integrations'].items())}
            </table>
        </div>
        
        <div class="section">
            <h3>📋 Recent Events</h3>
            <div class="event-log">
                {''.join(f'<div class="event-item">[{datetime.fromtimestamp(event["ts"]).strftime("%H:%M:%S")}] {event["type"]}: {event["data"]}</div>' for event in reversed(status['recent_events']))}
            </div>
        </div>
        
        <p style="text-align: center; color: #666; margin-top: 30px;">
            Auto-refresh every 30s
        </p>
    </div>
</body>
</html>
        """
        
        return html
        
    except Exception as e:
        return f"<html><body><h1>Error loading Phase 4 Watchdog</h1><p>{str(e)}</p></body></html>"


@app.route("/api/phase4/status")
def api_phase4_status():
    """API endpoint for Phase 4 status."""
    try:
        from src.phase4_watchdog import get_watchdog
        watchdog = get_watchdog()
        return jsonify(watchdog.get_status())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/phase5")
def phase5_dashboard():
    """Phase 5 Reliability dashboard page."""
    try:
        from src.phase5_reliability import get_phase5_reliability
        phase5 = get_phase5_reliability()
        status = phase5.get_status()
        
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Phase 5 Reliability - Trading Bot</title>
    <meta http-equiv="refresh" content="30">
    <style>
        body {{ font-family: monospace; background: #0a0a0a; color: #e0e0e0; padding: 20px; }}
        .container {{ max-width: 1600px; margin: 0 auto; }}
        .header {{ border-bottom: 2px solid #00ff00; padding-bottom: 10px; margin-bottom: 20px; }}
        .nav {{ margin-bottom: 20px; }}
        .nav a {{ color: #00ff00; text-decoration: none; padding: 10px 20px; background: #1a1a1a; border-radius: 5px; margin-right: 10px; }}
        .nav a:hover {{ background: #2a2a2a; }}
        .status-card {{ background: #1a1a1a; border: 2px solid {'#00ff88' if status['running'] else '#ff4466'}; padding: 20px; border-radius: 10px; margin-bottom: 20px; }}
        .status-title {{ font-size: 2em; color: {'#00ff88' if status['running'] else '#ff4466'}; }}
        .metric-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 20px; }}
        .metric-box {{ background: #1a1a1a; border: 1px solid #333; padding: 15px; border-radius: 5px; }}
        .metric-label {{ color: #888; font-size: 0.9em; }}
        .metric-value {{ font-size: 1.5em; font-weight: bold; }}
        .ok {{ color: #00ff88; }}
        .warn {{ color: #ffaa00; }}
        .critical {{ color: #ff4466; }}
        .section {{ background: #1a1a1a; border: 1px solid #333; padding: 20px; border-radius: 5px; margin-bottom: 20px; }}
        .section h3 {{ color: #00ff00; margin-top: 0; }}
        .slo-bar {{ width: 100%; height: 30px; background: #333; border-radius: 5px; overflow: hidden; margin: 10px 0; }}
        .slo-fill {{ height: 100%; background: linear-gradient(90deg, #00ff88, #00ff00); transition: width 0.3s; }}
        .event-log {{ max-height: 300px; overflow-y: auto; font-size: 0.9em; }}
        .event-item {{ padding: 8px; margin: 4px 0; background: #1a1a1a; border-left: 3px solid #00ff88; }}
        .event-item.alert {{ border-left-color: #ff4466; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #333; }}
        th {{ color: #00ff00; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🛡️ Phase 5 Reliability Engineering</h1>
        </div>
        
        <div class="nav">
            <a href="/">← Main Dashboard</a>
            <a href="/phase2">Phase 2</a>
            <a href="/phase3">Phase 3</a>
            <a href="/phase4">Phase 4</a>
            <a href="/health">Health Check</a>
        </div>
        
        <div class="status-card">
            <div class="status-title">{'🟢 OPERATIONAL' if status['running'] else '🔴 STOPPED'}</div>
            <p style="color: #888; margin-top: 10px;">
                Canary Mode: {'ACTIVE' if status['canary_mode'] else 'Inactive'}
            </p>
        </div>
        
        <div class="section">
            <h3>📊 SLO Compliance (30-min rolling window)</h3>
            {f'''
            <div style="margin-bottom: 15px;">
                <div style="display: flex; justify-content: space-between; margin-bottom: 5px;">
                    <span>Uptime: {status['recent_slo']['uptime_pct']:.2f}%</span>
                    <span>Target: {status['slo_targets']['uptime_pct']:.1f}%</span>
                </div>
                <div class="slo-bar">
                    <div class="slo-fill" style="width: {status['recent_slo']['uptime_pct']}%;"></div>
                </div>
            </div>
            <div style="margin-bottom: 15px;">
                <div style="display: flex; justify-content: space-between; margin-bottom: 5px;">
                    <span>Error Rate: {status['recent_slo']['error_rate_pct']:.2f}%</span>
                    <span>Target: &lt; {status['slo_targets']['error_rate_pct']:.1f}%</span>
                </div>
                <div class="slo-bar">
                    <div class="slo-fill" style="width: {max(0, 100 - status['recent_slo']['error_rate_pct'] * 20)}%;"></div>
                </div>
            </div>
            <div style="margin-bottom: 15px;">
                <div style="display: flex; justify-content: space-between; margin-bottom: 5px;">
                    <span>P95 Latency: {status['recent_slo']['latency_ms_p95']:.0f}ms</span>
                    <span>Target: &lt; {status['slo_targets']['latency_ms_p95']:.0f}ms</span>
                </div>
                <div class="slo-bar">
                    <div class="slo-fill" style="width: {max(0, 100 - (status['recent_slo']['latency_ms_p95'] / status['slo_targets']['latency_ms_p95']) * 100)}%;"></div>
                </div>
            </div>
            ''' if status['recent_slo'] else '<p style="color: #666;">No SLO data yet...</p>'}
        </div>
        
        <div class="metric-grid">
            <div class="metric-box">
                <div class="metric-label">SLO Samples</div>
                <div class="metric-value ok">{status['slo_samples_count']}</div>
            </div>
            <div class="metric-box">
                <div class="metric-label">SLO Breaches</div>
                <div class="metric-value {'critical' if status['slo_breaches'] > 0 else 'ok'}">{status['slo_breaches']}</div>
            </div>
            <div class="metric-box">
                <div class="metric-label">Chaos Events</div>
                <div class="metric-value warn">{status['chaos_events']}</div>
            </div>
            <div class="metric-box">
                <div class="metric-label">Reconciliations</div>
                <div class="metric-value ok">{status['recon_results']}</div>
            </div>
            <div class="metric-box">
                <div class="metric-label">Backups</div>
                <div class="metric-value ok">{status['backups_count']}</div>
            </div>
            <div class="metric-box">
                <div class="metric-label">Config Drifts</div>
                <div class="metric-value {'warn' if status['config_drifts'] > 0 else 'ok'}">{status['config_drifts']}</div>
            </div>
            <div class="metric-box">
                <div class="metric-label">Duplicate Guards</div>
                <div class="metric-value ok">{status['duplicate_guards']}</div>
            </div>
        </div>
        
        <div class="section">
            <h3>🔥 Recent Chaos Events</h3>
            <div class="event-log">
                {''.join(f'<div class="event-item">[{datetime.fromtimestamp(event["ts"]).strftime("%H:%M:%S")}] {event["type"]}: {event.get("params", {})}</div>' for event in reversed(status['recent_chaos'])) if status['recent_chaos'] else '<p style="color: #666;">No chaos events yet</p>'}
            </div>
        </div>
        
        <div class="section">
            <h3>🔄 Recent Reconciliations</h3>
            <div class="event-log">
                {''.join(f'<div class="event-item">[{datetime.fromtimestamp(recon["ts"]).strftime("%H:%M:%S")}] Positions: {recon.get("positions_checked", "N/A")}</div>' for recon in reversed(status['recent_recons'])) if status['recent_recons'] else '<p style="color: #666;">No reconciliations yet</p>'}
            </div>
        </div>
        
        {f'''
        <div class="section">
            <h3>⚠️ SLO Breaches</h3>
            <div class="event-log">
                {''.join(f'<div class="event-item alert">[{datetime.fromtimestamp(breach["ts"]).strftime("%H:%M:%S")}] {", ".join(breach["reasons"])}</div>' for breach in reversed(status['recent_breaches']))}
            </div>
        </div>
        ''' if status['recent_breaches'] else ''}
        
        {f'''
        <div class="section">
            <h3>⚠️ Config Drifts</h3>
            <div class="event-log">
                {''.join(f'<div class="event-item alert">[{datetime.fromtimestamp(drift["ts"]).strftime("%H:%M:%S")}] {drift["file"]}</div>' for drift in reversed(status['recent_drifts']))}
            </div>
        </div>
        ''' if status['recent_drifts'] else ''}
        
        <p style="text-align: center; color: #666; margin-top: 30px;">
            Auto-refresh every 30s
        </p>
    </div>
</body>
</html>
        """
        
        return html
        
    except Exception as e:
        return f"<html><body><h1>Error loading Phase 5 Reliability</h1><p>{str(e)}</p></body></html>"


@app.route("/api/phase5/status")
def api_phase5_status():
    """API endpoint for Phase 5 status."""
    try:
        from src.phase5_reliability import get_phase5_reliability
        phase5 = get_phase5_reliability()
        return jsonify(phase5.get_status())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/phase6")
def phase6_dashboard():
    """Phase 6 Alpha Engine dashboard page."""
    try:
        from src.phase6_alpha_engine import get_phase6_alpha_engine
        phase6 = get_phase6_alpha_engine()
        status = phase6.get_status()
        
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Phase 6 Alpha Engine - Trading Bot</title>
    <meta http-equiv="refresh" content="30">
    <style>
        body {{ font-family: monospace; background: #0a0a0a; color: #e0e0e0; padding: 20px; }}
        .container {{ max-width: 1600px; margin: 0 auto; }}
        .header {{ border-bottom: 2px solid #00ff00; padding-bottom: 10px; margin-bottom: 20px; }}
        .nav {{ margin-bottom: 20px; }}
        .nav a {{ color: #00ff00; text-decoration: none; padding: 10px 20px; background: #1a1a1a; border-radius: 5px; margin-right: 10px; }}
        .nav a:hover {{ background: #2a2a2a; }}
        .status-card {{ background: #1a1a1a; border: 2px solid {'#00ff88' if status['running'] else '#ff4466'}; padding: 20px; border-radius: 10px; margin-bottom: 20px; }}
        .status-title {{ font-size: 2em; color: {'#00ff88' if status['running'] else '#ff4466'}; }}
        .metric-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 20px; }}
        .metric-box {{ background: #1a1a1a; border: 1px solid #333; padding: 15px; border-radius: 5px; }}
        .metric-label {{ color: #888; font-size: 0.9em; }}
        .metric-value {{ font-size: 1.5em; font-weight: bold; }}
        .ok {{ color: #00ff88; }}
        .warn {{ color: #ffaa00; }}
        .promote {{ color: #00ff88; }}
        .demote {{ color: #ff4466; }}
        .hold {{ color: #888; }}
        .section {{ background: #1a1a1a; border: 1px solid #333; padding: 20px; border-radius: 5px; margin-bottom: 20px; }}
        .section h3 {{ color: #00ff00; margin-top: 0; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #333; }}
        th {{ color: #00ff00; }}
        .event-log {{ max-height: 300px; overflow-y: auto; font-size: 0.9em; }}
        .event-item {{ padding: 8px; margin: 4px 0; background: #1a1a1a; border-left: 3px solid #00ff88; }}
        .badge {{ display: inline-block; padding: 3px 8px; border-radius: 3px; font-size: 0.85em; margin-left: 5px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎯 Phase 6 Alpha Engine</h1>
        </div>
        
        <div class="nav">
            <a href="/">← Main Dashboard</a>
            <a href="/phase2">Phase 2</a>
            <a href="/phase3">Phase 3</a>
            <a href="/phase4">Phase 4</a>
            <a href="/phase5">Phase 5</a>
            <a href="/health">Health Check</a>
        </div>
        
        <div class="status-card">
            <div class="status-title">{'🟢 OPERATIONAL' if status['running'] else '🔴 STOPPED'}</div>
            <p style="color: #888; margin-top: 10px;">
                Ensemble Threshold: {status['min_ensemble_score']:.0%} | Families: {len(status['alpha_families'])}
            </p>
        </div>
        
        <div class="metric-grid">
            <div class="metric-box">
                <div class="metric-label">Alpha Decisions</div>
                <div class="metric-value ok">{status['alpha_decisions_count']}</div>
            </div>
            <div class="metric-box">
                <div class="metric-label">Event Blocks</div>
                <div class="metric-value warn">{status['event_blocks_count']}</div>
            </div>
            <div class="metric-box">
                <div class="metric-label">RL Updates</div>
                <div class="metric-value ok">{status['rl_updates_count']}</div>
            </div>
            <div class="metric-box">
                <div class="metric-label">Total Trades</div>
                <div class="metric-value ok">{status['total_trades']}</div>
            </div>
            <div class="metric-box">
                <div class="metric-label">Max Symbols</div>
                <div class="metric-value ok">{status['max_symbols_in_parallel']}</div>
            </div>
            <div class="metric-box">
                <div class="metric-label">Profit Lock</div>
                <div class="metric-value {'ok' if status['profit_lock_enabled'] else 'warn'}">{'ON' if status['profit_lock_enabled'] else 'OFF'}</div>
            </div>
        </div>
        
        <div class="section">
            <h3>🧪 Alpha Lab (A/B Testing)</h3>
            <table>
                <tr><th>Family</th><th>Score</th><th>Trades</th><th>Expectancy</th><th>Decision</th></tr>
                {''.join(f'<tr><td>{name}</td><td>{arm["score"]:.2f}</td><td>{arm["trades"]}</td><td>${arm["expectancy_usd"]:.2f}</td><td class="{status["lab_decisions"].get(name, "hold")}">{status["lab_decisions"].get(name, "hold").upper()}</td></tr>' for name, arm in status['lab_arms'].items()) if status['lab_arms'] else '<tr><td colspan="5" style="text-align: center; color: #666;">No lab data yet</td></tr>'}
            </table>
        </div>
        
        <div class="section">
            <h3>🎯 Tiered Performance (24h)</h3>
            <table>
                <tr><th>Tier</th><th>Symbols</th><th>P&L</th><th>Win Rate</th><th>Trades</th><th>Ensemble P50/P75</th><th>Slippage P50/P75</th><th>Top Blocks</th></tr>
                {'<tr><td style="color: #00ff88;">MAJORS</td><td>' + ", ".join(status.get("tier_metrics", {}).get("majors", {}).get("symbols", [])) + '</td><td class="' + ("ok" if status.get("tier_metrics", {}).get("majors", {}).get("pnl_usd", 0) >= 0 else "warn") + '">$' + f'{status.get("tier_metrics", {}).get("majors", {}).get("pnl_usd", 0):.2f}' + '</td><td>' + f'{status.get("tier_metrics", {}).get("majors", {}).get("winrate", 0):.1%}' + '</td><td>' + str(status.get("tier_metrics", {}).get("majors", {}).get("trades", 0)) + '</td><td>' + f'{status.get("tier_metrics", {}).get("majors", {}).get("ensemble_p50", 0):.2f}' + ' / ' + f'{status.get("tier_metrics", {}).get("majors", {}).get("ensemble_p75", 0):.2f}' + '</td><td>' + f'{status.get("tier_metrics", {}).get("majors", {}).get("slippage_p50_bps", 0):.1f}' + ' / ' + f'{status.get("tier_metrics", {}).get("majors", {}).get("slippage_p75_bps", 0):.1f}bps' + '</td><td>' + (", ".join(status.get("tier_metrics", {}).get("majors", {}).get("top_block_reasons", [])[:3]) if status.get("tier_metrics", {}).get("majors", {}).get("top_block_reasons") else "-") + '</td></tr>' if "tier_metrics" in status and "majors" in status.get("tier_metrics", {}) else ''}
                {'<tr><td style="color: #00ddff;">L1s</td><td>' + ", ".join(status.get("tier_metrics", {}).get("l1s", {}).get("symbols", [])) + '</td><td class="' + ("ok" if status.get("tier_metrics", {}).get("l1s", {}).get("pnl_usd", 0) >= 0 else "warn") + '">$' + f'{status.get("tier_metrics", {}).get("l1s", {}).get("pnl_usd", 0):.2f}' + '</td><td>' + f'{status.get("tier_metrics", {}).get("l1s", {}).get("winrate", 0):.1%}' + '</td><td>' + str(status.get("tier_metrics", {}).get("l1s", {}).get("trades", 0)) + '</td><td>' + f'{status.get("tier_metrics", {}).get("l1s", {}).get("ensemble_p50", 0):.2f}' + ' / ' + f'{status.get("tier_metrics", {}).get("l1s", {}).get("ensemble_p75", 0):.2f}' + '</td><td>' + f'{status.get("tier_metrics", {}).get("l1s", {}).get("slippage_p50_bps", 0):.1f}' + ' / ' + f'{status.get("tier_metrics", {}).get("l1s", {}).get("slippage_p75_bps", 0):.1f}bps' + '</td><td>' + (", ".join(status.get("tier_metrics", {}).get("l1s", {}).get("top_block_reasons", [])[:3]) if status.get("tier_metrics", {}).get("l1s", {}).get("top_block_reasons") else "-") + '</td></tr>' if "tier_metrics" in status and "l1s" in status.get("tier_metrics", {}) else ''}
                {'<tr><td style="color: #ffaa00;">EXPERIMENTAL</td><td>' + ", ".join(status.get("tier_metrics", {}).get("experimental", {}).get("symbols", [])) + '</td><td class="' + ("ok" if status.get("tier_metrics", {}).get("experimental", {}).get("pnl_usd", 0) >= 0 else "warn") + '">$' + f'{status.get("tier_metrics", {}).get("experimental", {}).get("pnl_usd", 0):.2f}' + '</td><td>' + f'{status.get("tier_metrics", {}).get("experimental", {}).get("winrate", 0):.1%}' + '</td><td>' + str(status.get("tier_metrics", {}).get("experimental", {}).get("trades", 0)) + '</td><td>' + f'{status.get("tier_metrics", {}).get("experimental", {}).get("ensemble_p50", 0):.2f}' + ' / ' + f'{status.get("tier_metrics", {}).get("experimental", {}).get("ensemble_p75", 0):.2f}' + '</td><td>' + f'{status.get("tier_metrics", {}).get("experimental", {}).get("slippage_p50_bps", 0):.1f}' + ' / ' + f'{status.get("tier_metrics", {}).get("experimental", {}).get("slippage_p75_bps", 0):.1f}bps' + '</td><td>' + (", ".join(status.get("tier_metrics", {}).get("experimental", {}).get("top_block_reasons", [])[:3]) if status.get("tier_metrics", {}).get("experimental", {}).get("top_block_reasons") else "-") + '</td></tr>' if "tier_metrics" in status and "experimental" in status.get("tier_metrics", {}) else ''}
            </table>
        </div>
        
        <div class="section">
            <h3>📈 Alpha Families</h3>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px;">
                {''.join(f'<div style="background: #1a1a1a; border: 1px solid #333; padding: 10px; border-radius: 5px; text-align: center;"><div style="color: #00ff00; font-weight: bold;">{fam.upper()}</div><div style="color: #888; font-size: 0.9em; margin-top: 5px;">Active</div></div>' for fam in status['alpha_families'])}
            </div>
        </div>
        
        <div class="section">
            <h3>🎯 Recent Alpha Decisions</h3>
            <div class="event-log">
                {''.join(f'<div class="event-item">[{datetime.fromtimestamp(dec["ts"]).strftime("%H:%M:%S")}] {dec["symbol"]}: Ensemble {dec["ensemble"]:.2%} | Route: {dec["route"]}</div>' for dec in reversed(status['recent_alpha_decisions'])) if status['recent_alpha_decisions'] else '<p style="color: #666;">No decisions yet</p>'}
            </div>
        </div>
        
        <div class="section">
            <h3>🚫 Recent Event Blocks</h3>
            <div class="event-log">
                {''.join(f'<div class="event-item">[{datetime.fromtimestamp(block["ts"]).strftime("%H:%M:%S")}] {block["symbol"]}: {block["reason"]}</div>' for block in reversed(status['recent_event_blocks'])) if status['recent_event_blocks'] else '<p style="color: #666;">No blocks yet</p>'}
            </div>
        </div>
        
        {f'''
        <div class="section">
            <h3>🤖 RL Policy Updates</h3>
            <div class="event-log">
                {''.join(f'<div class="event-item">[{datetime.fromtimestamp(update["ts"]).strftime("%H:%M:%S")}] Sharpe: {update["sharpe"]:.3f} | Sortino: {update["sortino"]:.3f} | DD: {update["drawdown_bps"]:.0f}bps</div>' for update in reversed(status['recent_rl_updates']))}
            </div>
        </div>
        ''' if status['recent_rl_updates'] else ''}
        
        <p style="text-align: center; color: #666; margin-top: 30px;">
            Auto-refresh every 30s
        </p>
    </div>
</body>
</html>
        """
        
        return html
        
    except Exception as e:
        return f"<html><body><h1>Error loading Phase 6 Alpha Engine</h1><p>{str(e)}</p></body></html>"


@app.route("/api/phase6/status")
def api_phase6_status():
    """API endpoint for Phase 6 status."""
    try:
        from src.phase6_alpha_engine import get_phase6_alpha_engine
        phase6 = get_phase6_alpha_engine()
        return jsonify(phase6.get_status())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/phase7")
def phase7_dashboard():
    """Phase 7 Predictive Intelligence dashboard page."""
    try:
        from src.phase7_predictive_intelligence import Phase7PredictiveIntelligence
        from src.phase7_predictive_intelligence import TIERS
        
        phase7 = Phase7PredictiveIntelligence()
        status = phase7.get_status()
        
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Phase 7 - Predictive Intelligence</title>
    <meta http-equiv="refresh" content="30">
    <style>
        body {{ font-family: monospace; background: #0a0a0a; color: #00ff00; padding: 20px; }}
        .container {{ max-width: 1600px; margin: 0 auto; }}
        .header {{ border-bottom: 2px solid #00ff00; padding-bottom: 10px; margin-bottom: 20px; }}
        .section {{ background: #1a1a1a; border: 1px solid #333; padding: 20px; margin: 20px 0; border-radius: 5px; }}
        .metric-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin: 20px 0; }}
        .metric-box {{ background: #1a1a1a; border: 1px solid #333; padding: 15px; text-align: center; }}
        .metric-label {{ color: #888; font-size: 0.9em; margin-bottom: 5px; }}
        .metric-value {{ color: #00ff00; font-size: 1.8em; font-weight: bold; }}
        .ok {{ color: #00ff00; }}
        .warn {{ color: #ffaa00; }}
        .alert {{ color: #ff0000; }}
        table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
        th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #333; }}
        th {{ background: #0a0a0a; color: #00ff00; }}
        .tier-majors {{ color: #00ff88; font-weight: bold; }}
        .tier-l1s {{ color: #00ddff; font-weight: bold; }}
        .tier-exp {{ color: #ffaa00; font-weight: bold; }}
        .weight-bar {{ height: 20px; background: #333; position: relative; margin-top: 5px; }}
        .weight-fill {{ height: 100%; background: linear-gradient(90deg, #00ff00, #00aa00); }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🔮 PHASE 7: Predictive Intelligence & Attribution-Driven Scaling</h1>
            <p>
                Status: <span class="{'ok' if status['running'] else 'alert'}">{'RUNNING' if status['running'] else 'OFFLINE'}</span> | 
                Regime: {status['regime']['name'].upper()} ({status['regime']['confidence']:.0%}) | 
                Focus: {len(status['focus_symbols'])} symbols
            </p>
        </div>
        
        <div class="metric-grid">
            <div class="metric-box">
                <div class="metric-label">Cross-Tier Enabled</div>
                <div class="metric-value {'ok' if status['cross_tier']['enabled'] else 'warn'}">{'ON' if status['cross_tier']['enabled'] else 'OFF'}</div>
            </div>
            <div class="metric-box">
                <div class="metric-label">Instability Score</div>
                <div class="metric-value {
                    'ok' if status['cross_tier']['instability_score'] < 0.5 else 
                    'warn' if status['cross_tier']['instability_score'] < status['cross_tier']['threshold'] else 
                    'alert'
                }">{status['cross_tier']['instability_score']:.3f}</div>
            </div>
            <div class="metric-box">
                <div class="metric-label">Predictive Events</div>
                <div class="metric-value {'ok' if status['predictive_events']['enabled'] else 'warn'}">{'ON' if status['predictive_events']['enabled'] else 'OFF'}</div>
            </div>
            <div class="metric-box">
                <div class="metric-label">Event Blocks</div>
                <div class="metric-value warn">{status['event_blocks_count']}</div>
            </div>
        </div>
        
        <div class="section">
            <h3>🌍 Regime-Aware Ensemble Weighting</h3>
            <div style="margin: 15px 0;">
                <p><strong>Current Regime:</strong> <span style="color: #00ff88;">{status['regime']['name'].upper()}</span></p>
                <p><strong>Confidence:</strong> {status['regime']['confidence']:.1%} | <strong>Samples:</strong> {status['regime']['samples']}</p>
            </div>
            <table>
                <tr><th>Alpha Family</th><th>Weight</th><th>Visual</th></tr>
                {chr(10).join(f'''<tr>
                    <td>{fam.upper()}</td>
                    <td>{weight:.2f}x</td>
                    <td><div class="weight-bar"><div class="weight-fill" style="width: {min(100, weight * 50)}%"></div></div></td>
                </tr>''' for fam, weight in status['regime']['weights'].items())}
            </table>
        </div>
        
        <div class="section">
            <h3>🎯 Tiered Capital Ramp Controller</h3>
            <table>
                <tr><th>Tier</th><th>Stage</th><th>Current Leverage</th><th>Progress</th><th>Elapsed</th></tr>
                {f'''<tr>
                    <td class="tier-majors">MAJORS</td>
                    <td>{status['capital_ramp']['majors']['stage']} / {status['capital_ramp']['majors']['total_stages']}</td>
                    <td>{status['capital_ramp']['majors']['current_leverage']:.1f}x</td>
                    <td>{min(100, (status['capital_ramp']['majors']['elapsed_hours'] / status['capital_ramp']['majors']['duration_hours']) * 100):.0f}%</td>
                    <td>{status['capital_ramp']['majors']['elapsed_hours']:.1f}h / {status['capital_ramp']['majors']['duration_hours']:.0f}h</td>
                </tr>'''}
                {f'''<tr>
                    <td class="tier-l1s">L1s</td>
                    <td>{status['capital_ramp']['l1s']['stage']} / {status['capital_ramp']['l1s']['total_stages']}</td>
                    <td>{status['capital_ramp']['l1s']['current_leverage']:.1f}x</td>
                    <td>{min(100, (status['capital_ramp']['l1s']['elapsed_hours'] / status['capital_ramp']['l1s']['duration_hours']) * 100):.0f}%</td>
                    <td>{status['capital_ramp']['l1s']['elapsed_hours']:.1f}h / {status['capital_ramp']['l1s']['duration_hours']:.0f}h</td>
                </tr>'''}
                {f'''<tr>
                    <td class="tier-exp">EXPERIMENTAL</td>
                    <td>{status['capital_ramp']['experimental']['stage']} / {status['capital_ramp']['experimental']['total_stages']}</td>
                    <td>{status['capital_ramp']['experimental']['current_leverage']:.1f}x</td>
                    <td>{min(100, (status['capital_ramp']['experimental']['elapsed_hours'] / status['capital_ramp']['experimental']['duration_hours']) * 100):.0f}%</td>
                    <td>{status['capital_ramp']['experimental']['elapsed_hours']:.1f}h / {status['capital_ramp']['experimental']['duration_hours']:.0f}h</td>
                </tr>'''}
            </table>
        </div>
        
        <div class="section">
            <h3>📊 Alpha Family Attribution (24h)</h3>
            {chr(10).join(f'''
            <h4 class="tier-{tier}">{tier.upper()}</h4>
            <table>
                <tr><th>Symbol</th><th>P&L</th><th>Ensemble</th><th>Momentum</th><th>Mean Rev</th><th>Flow</th><th>Micro</th><th>Regime</th><th>Funding</th></tr>
                {chr(10).join('<tr><td>' + item['symbol'] + '</td><td class="' + ("ok" if item['pnl_usd'] >= 0 else "warn") + '">$' + f'{item["pnl_usd"]:.2f}' + '</td><td>' + f'{item["ensemble_p75"]:.2f}' + '</td><td>$' + f'{item["contrib"]["momentum"]:.2f}' + '</td><td>$' + f'{item["contrib"]["mean_reversion"]:.2f}' + '</td><td>$' + f'{item["contrib"]["flow"]:.2f}' + '</td><td>$' + f'{item["contrib"]["microstructure"]:.2f}' + '</td><td>$' + f'{item["contrib"]["regime"]:.2f}' + '</td><td>$' + f'{item["contrib"]["carry_funding"]:.2f}' + '</td></tr>' for item in panel)}
            </table>
            ''' for tier, panel in status['attribution_data'].items())}
        </div>
        
        <div class="section">
            <h3>🎯 Profitability Concentration</h3>
            <p><strong>Focus Symbols:</strong> {', '.join(status['focus_symbols']) if status['focus_symbols'] else 'None'}</p>
            <p><strong>Config:</strong> Top {status['focus_config']['top_per_tier']} per tier | Min Ensemble: {status['focus_config']['min_ensemble']:.0%}</p>
        </div>
        
        <div class="section">
            <h3>⚙️ Predictive Event Configuration</h3>
            <table>
                <tr><th>Event Type</th><th>Lookahead (min)</th><th>Status</th></tr>
                <tr><td>Funding Flip</td><td>{status['predictive_events']['funding_lookahead_min']}</td><td class="ok">ACTIVE</td></tr>
                <tr><td>Macro Calendar</td><td>{status['predictive_events']['macro_lookahead_min']}</td><td class="ok">ACTIVE</td></tr>
                <tr><td>Exchange Incident</td><td>{status['predictive_events']['incident_lookahead_min']}</td><td class="ok">ACTIVE</td></tr>
            </table>
        </div>
        
        <p style="text-align: center; color: #666; margin-top: 30px;">
            Auto-refresh every 30s | Regime History: {status['regime_history_count']} | Instability: {status['instability_history_count']}
        </p>
    </div>
</body>
</html>
        """
        
        return html
        
    except Exception as e:
        return f"<html><body><h1>Error loading Phase 7 Predictive Intelligence</h1><p>{str(e)}</p><pre>{traceback.format_exc()}</pre></body></html>"


@app.route("/api/phase7/status")
def api_phase7_status():
    """API endpoint for Phase 7 status."""
    try:
        from src.phase7_predictive_intelligence import Phase7PredictiveIntelligence
        phase7 = Phase7PredictiveIntelligence()
        return jsonify(phase7.get_status())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/phase75/status")
def api_phase75_status():
    """API endpoint for Phase 7.5 Outcome Monitor status."""
    try:
        from src.phase75_monitor import get_phase75_monitor
        monitor = get_phase75_monitor()
        status = monitor.get_status()
        
        telemetry = {}
        for tier in ["majors", "l1s", "experimental"]:
            telemetry[tier] = {
                "execution_rate": monitor.execution_rate_24h_tier(tier),
                "realized_rr": monitor.realized_rr_24h_tier(tier),
                "slippage_p75_bps": monitor.slippage_p75_bps_tier(tier)
            }
        
        return jsonify({
            "status": "success",
            "data": {
                **status,
                "telemetry": telemetry,
                "drawdown_pct": monitor.rolling_drawdown_pct_24h(),
                "config": {
                    "exec_target_min": monitor.config.exec_target_min,
                    "exec_target_max": monitor.config.exec_target_max,
                    "rr_min_tier": monitor.config.rr_min_tier,
                    "slip_cap_tier": monitor.config.slip_cap_tier,
                    "max_drawdown_pct": monitor.config.max_drawdown_pct
                }
            }
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/phase76/status")
def api_phase76_status():
    """API endpoint for Phase 7.6 Performance Patch status."""
    try:
        from src.phase76_performance import get_phase76_performance
        performance = get_phase76_performance()
        status = performance.get_status()
        
        return jsonify({
            "status": "success",
            "data": status
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/phase80/status")
def api_phase80_status():
    """API endpoint for Phase 8.0 Full Autonomy status."""
    try:
        from src.phase80_coordinator import get_phase80_coordinator
        coordinator = get_phase80_coordinator()
        status = coordinator.get_status()
        
        return jsonify({
            "status": "success",
            "data": status
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/phase81/status")
def api_phase81_status():
    """API endpoint for Phase 8.1 Edge Compounding status."""
    try:
        from src.phase81_edge_compounding import get_phase81_status
        status = get_phase81_status()
        
        return jsonify({
            "status": "success",
            "data": status
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/phase82/status")
def api_phase82_status():
    """API endpoint for Phase 8.2 Go-Live Controller status."""
    try:
        from src.phase82_go_live import get_phase82_status
        status = get_phase82_status()
        
        return jsonify({
            "status": "success",
            "data": status
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/phase82/validate", methods=["GET"])
def api_phase82_validate():
    """API endpoint for running Phase 8.2 validation drills."""
    try:
        from src.phase82_validation import run_full_validation_suite, DRILLS
        
        drill_name = request.args.get("drill", "all")
        
        if drill_name == "all":
            suite = run_full_validation_suite()
            return jsonify({
                "status": "success",
                "started_ts": suite.started_ts,
                "finished_ts": suite.finished_ts,
                "duration_sec": round(suite.finished_ts - suite.started_ts, 2),
                "results": [{"name": r.name, "passed": r.passed, "details": r.details} for r in suite.results],
                "all_passed": suite.all_passed
            })
        else:
            fn = DRILLS.get(drill_name)
            if not fn:
                return jsonify({"status": "error", "error": f"Unknown drill '{drill_name}'"}), 400
            
            res = fn()
            return jsonify({
                "status": "success",
                "name": res.name,
                "passed": res.passed,
                "details": res.details
            })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/phase82/validation/status")
def api_phase82_validation_status():
    """API endpoint for Phase 8.2 validation harness status."""
    try:
        from src.phase82_validation import get_validation_status
        status = get_validation_status()
        
        return jsonify({
            "status": "success",
            "data": status
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/phase83/status")
def api_phase83_status():
    """API endpoint for Phase 8.3 Drift Detector status."""
    try:
        from src.phase83_drift_detector import get_phase83_status
        status = get_phase83_status()
        
        return jsonify({
            "status": "success",
            "data": status
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/phase84/status")
def api_phase84_status():
    """API endpoint for Phase 8.4 Profit Optimizer status."""
    try:
        from src.phase84_86_expansion import get_phase84_status
        status = get_phase84_status()
        
        return jsonify({
            "status": "success",
            "data": status
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/phase85/status")
def api_phase85_status():
    """API endpoint for Phase 8.5 Predictive Intelligence status."""
    try:
        from src.phase84_86_expansion import get_phase85_status
        status = get_phase85_status()
        
        return jsonify({
            "status": "success",
            "data": status
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/phase86/status")
def api_phase86_status():
    """API endpoint for Phase 8.6 Institutional Risk Layer status."""
    try:
        from src.phase84_86_expansion import get_phase86_status
        status = get_phase86_status()
        
        return jsonify({
            "status": "success",
            "data": status
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/phase87/status")
def api_phase87_status():
    """API endpoint for Phase 8.7 Transparency & Audit status."""
    try:
        from src.phase87_89_expansion import get_phase87_status
        status = get_phase87_status()
        
        return jsonify({
            "status": "success",
            "data": status
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/phase88/status")
def api_phase88_status():
    """API endpoint for Phase 8.8 Collaborative Intelligence status."""
    try:
        from src.phase87_89_expansion import get_phase88_status
        status = get_phase88_status()
        
        return jsonify({
            "status": "success",
            "data": status
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/phase89/status")
def api_phase89_status():
    """API endpoint for Phase 8.9 External Signal Integration status."""
    try:
        from src.phase87_89_expansion import get_phase89_status
        status = get_phase89_status()
        
        return jsonify({
            "status": "success",
            "data": status
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/phase9/status")
def api_phase9_status():
    """API endpoint for Phase 9 Autonomy Controller status."""
    try:
        from src.phase9_autonomy import get_phase9_status
        status = get_phase9_status()
        
        return jsonify({
            "status": "success",
            "data": status
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/phase91/status")
def api_phase91_status():
    """API endpoint for Phase 9.1 Adaptive Governance status."""
    try:
        from src.phase91_adaptive_governance import get_phase91_status
        status = get_phase91_status()
        
        return jsonify({
            "status": "success",
            "data": status
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


# ==============================
# Phase 9.1 Export Endpoints
# ==============================

@app.route("/api/export/health")
def api_export_health():
    """Export health data: composite score, trends, subsystem status."""
    try:
        from src.phase91_export_service import export_health
        data = export_health()
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/export/governance")
def api_export_governance():
    """Export governance events (ramps/shrinks) with optional time filter."""
    try:
        from src.phase91_export_service import get_governance_events
        since = request.args.get("since", type=int)
        events = get_governance_events(since)
        return jsonify(events)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/export/calibration")
def api_export_calibration():
    """Export calibration events with optional time filter."""
    try:
        from src.phase91_export_service import get_calibration_events
        since = request.args.get("since", type=int)
        events = get_calibration_events(since)
        return jsonify(events)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/export/tolerances")
def api_export_tolerances():
    """Export current drift tolerances and volatility index."""
    try:
        from src.phase91_export_service import export_tolerances
        data = export_tolerances()
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/export/attribution")
def api_export_attribution():
    """Export per-symbol and per-tier attribution data."""
    try:
        from src.phase91_export_service import export_attribution
        data = export_attribution()
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/export/audit")
def api_export_audit():
    """Export Phase 8.7 audit events with optional time filter."""
    try:
        from src.phase91_export_service import get_audit_events
        since = request.args.get("since", type=int)
        events = get_audit_events(since)
        return jsonify(events)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/phase91")
def phase91_cockpit():
    """Phase 9.1 Governance Cockpit - Real-time adaptive governance monitoring."""
    html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta http-equiv="refresh" content="30">
    <title>Phase 9.1 Governance Cockpit</title>
    <style>
        body {
            font-family: 'Courier New', monospace;
            background: #0a0a0a;
            color: #00ff00;
            padding: 20px;
            margin: 0;
        }
        .container {
            max-width: 1800px;
            margin: 0 auto;
        }
        .header {
            border-bottom: 2px solid #00ff00;
            padding-bottom: 15px;
            margin-bottom: 25px;
        }
        h1 {
            margin: 0;
            font-size: 28px;
        }
        .subtitle {
            color: #888;
            margin-top: 5px;
        }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }
        .card {
            background: #1a1a1a;
            border: 1px solid #00ff00;
            border-radius: 8px;
            padding: 20px;
        }
        .card h2 {
            margin: 0 0 15px 0;
            font-size: 18px;
            border-bottom: 1px solid #333;
            padding-bottom: 10px;
        }
        .metric {
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid #222;
        }
        .metric:last-child {
            border-bottom: none;
        }
        .label {
            color: #888;
        }
        .value {
            color: #00ff00;
            font-weight: bold;
        }
        .status-ok {
            color: #00ff00;
        }
        .status-warning {
            color: #ffaa00;
        }
        .status-error {
            color: #ff0000;
        }
        .timeline {
            max-height: 300px;
            overflow-y: auto;
        }
        .event {
            padding: 10px;
            margin-bottom: 10px;
            background: #151515;
            border-left: 3px solid #00ff00;
            font-size: 12px;
        }
        .event-timestamp {
            color: #666;
        }
        .attribution-table {
            width: 100%;
            font-size: 12px;
        }
        .attribution-table td {
            padding: 5px;
        }
        .positive {
            color: #00ff00;
        }
        .negative {
            color: #ff6600;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🧠 PHASE 9.1: Adaptive Governance Cockpit</h1>
            <p class="subtitle">Real-time adaptive governance | Self-optimizing tolerances | Health-weighted execution</p>
        </div>

        <div class="grid">
            <!-- Health Trends Card -->
            <div class="card">
                <h2>📊 Health Trends</h2>
                <div id="health-content">Loading...</div>
            </div>

            <!-- Tolerances Card -->
            <div class="card">
                <h2>⚙️ Dynamic Tolerances</h2>
                <div id="tolerances-content">Loading...</div>
            </div>

            <!-- Subsystems Card -->
            <div class="card">
                <h2>🛡️ Subsystem Health</h2>
                <div id="subsystems-content">Loading...</div>
            </div>

            <!-- Attribution Card -->
            <div class="card">
                <h2>💰 Attribution</h2>
                <div id="attribution-content">Loading...</div>
            </div>
        </div>

        <!-- Governance Timeline -->
        <div class="card">
            <h2>📜 Governance Events (Last 24h)</h2>
            <div id="governance-timeline" class="timeline">Loading...</div>
        </div>

        <!-- Calibration Timeline -->
        <div class="card">
            <h2>🎯 Calibration History (Last 24h)</h2>
            <div id="calibration-timeline" class="timeline">Loading...</div>
        </div>
    </div>

    <script>
        function formatTimestamp(ts) {
            const date = new Date(ts * 1000);
            return date.toLocaleString();
        }

        function updateHealth() {
            fetch('/api/export/health')
                .then(r => r.json())
                .then(data => {
                    const html = `
                        <div class="metric">
                            <span class="label">Current Health:</span>
                            <span class="value">${(data.current * 100).toFixed(1)}%</span>
                        </div>
                        <div class="metric">
                            <span class="label">1h Average:</span>
                            <span class="value">${(data.avg_1h * 100).toFixed(1)}%</span>
                        </div>
                        <div class="metric">
                            <span class="label">6h Average:</span>
                            <span class="value">${(data.avg_6h * 100).toFixed(1)}%</span>
                        </div>
                        <div class="metric">
                            <span class="label">24h Average:</span>
                            <span class="value">${(data.avg_24h * 100).toFixed(1)}%</span>
                        </div>
                    `;
                    document.getElementById('health-content').innerHTML = html;
                })
                .catch(e => {
                    document.getElementById('health-content').innerHTML = '<div class="status-error">Error loading health data</div>';
                });
        }

        function updateTolerances() {
            fetch('/api/export/tolerances')
                .then(r => r.json())
                .then(data => {
                    const html = `
                        <div class="metric">
                            <span class="label">Volatility Index:</span>
                            <span class="value">${(data.vol_index * 100).toFixed(1)}%</span>
                        </div>
                        <div class="metric">
                            <span class="label">EV Tolerance:</span>
                            <span class="value">$${data.ev_usd.toFixed(2)}</span>
                        </div>
                        <div class="metric">
                            <span class="label">Trailing R:</span>
                            <span class="value">${data.trailing_r.toFixed(2)}R</span>
                        </div>
                        <div class="metric">
                            <span class="label">Add R:</span>
                            <span class="value">${data.add_r.toFixed(2)}R</span>
                        </div>
                    `;
                    document.getElementById('tolerances-content').innerHTML = html;
                })
                .catch(e => {
                    document.getElementById('tolerances-content').innerHTML = '<div class="status-error">Error loading tolerances</div>';
                });
        }

        function updateSubsystems() {
            fetch('/api/export/health')
                .then(r => r.json())
                .then(data => {
                    const subsystems = data.subsystems || {};
                    let html = '';
                    for (const [name, status] of Object.entries(subsystems)) {
                        const statusClass = status === 'ok' ? 'status-ok' : (status === 'warning' ? 'status-warning' : 'status-error');
                        html += `
                            <div class="metric">
                                <span class="label">${name}:</span>
                                <span class="value ${statusClass}">${status.toUpperCase()}</span>
                            </div>
                        `;
                    }
                    document.getElementById('subsystems-content').innerHTML = html || '<div class="label">No subsystems data</div>';
                })
                .catch(e => {
                    document.getElementById('subsystems-content').innerHTML = '<div class="status-error">Error loading subsystems</div>';
                });
        }

        function updateAttribution() {
            fetch('/api/export/attribution')
                .then(r => r.json())
                .then(data => {
                    let html = '<table class="attribution-table">';
                    
                    // Per-tier attribution
                    const tiers = data.per_tier || {};
                    for (const [tier, pnl] of Object.entries(tiers)) {
                        const pnlClass = pnl >= 0 ? 'positive' : 'negative';
                        html += `<tr><td>${tier}:</td><td class="${pnlClass}">$${pnl.toFixed(2)}</td></tr>`;
                    }
                    
                    // Sharpe/Sortino
                    html += `<tr><td colspan="2" style="border-top: 1px solid #333; padding-top: 10px;"></td></tr>`;
                    html += `<tr><td>Sharpe:</td><td class="value">${data.sharpe.toFixed(2)}</td></tr>`;
                    html += `<tr><td>Sortino:</td><td class="value">${data.sortino.toFixed(2)}</td></tr>`;
                    
                    html += '</table>';
                    document.getElementById('attribution-content').innerHTML = html;
                })
                .catch(e => {
                    document.getElementById('attribution-content').innerHTML = '<div class="status-error">Error loading attribution</div>';
                });
        }

        function updateGovernance() {
            const since = Math.floor(Date.now() / 1000) - (24 * 3600);
            fetch('/api/export/governance?since=' + since)
                .then(r => r.json())
                .then(events => {
                    if (events.length === 0) {
                        document.getElementById('governance-timeline').innerHTML = '<div class="label">No governance events in last 24h</div>';
                        return;
                    }
                    let html = '';
                    events.reverse().forEach(event => {
                        html += `
                            <div class="event">
                                <div><strong>${event.action.toUpperCase()}</strong> - ${event.tier}</div>
                                <div>Step: ${(event.step_pct * 100).toFixed(1)}% | Health: ${(event.health * 100).toFixed(1)}%</div>
                                <div class="event-timestamp">${formatTimestamp(event.ts)}</div>
                            </div>
                        `;
                    });
                    document.getElementById('governance-timeline').innerHTML = html;
                })
                .catch(e => {
                    document.getElementById('governance-timeline').innerHTML = '<div class="status-error">Error loading governance events</div>';
                });
        }

        function updateCalibration() {
            const since = Math.floor(Date.now() / 1000) - (24 * 3600);
            fetch('/api/export/calibration?since=' + since)
                .then(r => r.json())
                .then(events => {
                    if (events.length === 0) {
                        document.getElementById('calibration-timeline').innerHTML = '<div class="label">No calibration events in last 24h</div>';
                        return;
                    }
                    let html = '';
                    events.reverse().forEach(event => {
                        html += `
                            <div class="event">
                                <div><strong>${event.tier}</strong> - Confidence: ${(event.confidence * 100).toFixed(1)}%</div>
                                <div>P&L: $${event.tier_pnl.toFixed(2)} | EV: ${event.ev_delta.toFixed(3)} | TR: ${event.tr_delta.toFixed(3)} | Add: ${event.add_delta.toFixed(3)}</div>
                                <div class="event-timestamp">${formatTimestamp(event.ts)}</div>
                            </div>
                        `;
                    });
                    document.getElementById('calibration-timeline').innerHTML = html;
                })
                .catch(e => {
                    document.getElementById('calibration-timeline').innerHTML = '<div class="status-error">Error loading calibration events</div>';
                });
        }

        // Initial load
        updateHealth();
        updateTolerances();
        updateSubsystems();
        updateAttribution();
        updateGovernance();
        updateCalibration();

        // Refresh every 10 seconds
        setInterval(() => {
            updateHealth();
            updateTolerances();
            updateSubsystems();
            updateAttribution();
            updateGovernance();
            updateCalibration();
        }, 10000);
    </script>
</body>
</html>
"""
    return html


@app.route("/phase3")
def phase3_dashboard():
    """Phase 3 dashboard page."""
    try:
        from src.phase3_integration import get_phase3_controller
        controller = get_phase3_controller()
        
        status = controller.get_status()
        
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Phase 3 Dashboard - Edge Compounding</title>
    <meta http-equiv="refresh" content="30">
    <style>
        body {{ font-family: monospace; background: #0a0a0a; color: #00ff00; padding: 20px; }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        .header {{ border-bottom: 2px solid #00ff00; padding-bottom: 10px; margin-bottom: 20px; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 15px; margin-bottom: 20px; }}
        .card {{ background: #1a1a1a; border: 1px solid #00ff00; padding: 15px; border-radius: 5px; }}
        .card h3 {{ margin-top: 0; color: #00ff00; border-bottom: 1px solid #333; padding-bottom: 5px; }}
        .metric {{ margin: 8px 0; }}
        .label {{ color: #888; display: inline-block; width: 180px; }}
        .value {{ color: #00ff00; font-weight: bold; }}
        .active {{ color: #00ff00; }}
        .inactive {{ color: #ff6600; }}
        .paused {{ color: #ffaa00; }}
        .progress-bar {{ width: 100%; height: 20px; background: #333; border-radius: 3px; margin-top: 5px; }}
        .progress-fill {{ height: 100%; background: linear-gradient(90deg, #00ff00, #00aa00); border-radius: 3px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>⚡ PHASE 3: Edge Compounding & Disciplined Scale</h1>
            <p>Adaptive Learning | Capital Ramp | Attribution-Driven Optimization</p>
        </div>
        
        <div class="grid">
            <div class="card">
                <h3>🔧 Adaptive Relaxation</h3>
                <div class="metric">
                    <span class="label">Status:</span>
                    <span class="value {'active' if status['relaxation']['active'] else 'inactive'}">
                        {'ACTIVE' if status['relaxation']['active'] else 'OFF'}
                    </span>
                </div>
                <div class="metric">
                    <span class="label">Policy:</span>
                    <span class="value">{status['relaxation']['policy'] or 'N/A'}</span>
                </div>
                <div class="metric">
                    <span class="label">Total Hours:</span>
                    <span class="value">{status['relaxation']['total_hours']:.1f}h</span>
                </div>
            </div>
            
            <div class="card">
                <h3>📉 Drawdown Control</h3>
                <div class="metric">
                    <span class="label">Current Drawdown:</span>
                    <span class="value">{status['drawdown']['current_bps']:.1f} bps</span>
                </div>
                <div class="metric">
                    <span class="label">Max Drawdown:</span>
                    <span class="value">{status['drawdown']['max_bps']:.1f} bps</span>
                </div>
                <div class="metric">
                    <span class="label">Soft Block:</span>
                    <span class="value {'active' if status['drawdown']['soft_block_active'] else 'inactive'}">
                        {'ACTIVE' if status['drawdown']['soft_block_active'] else 'OFF'}
                    </span>
                </div>
            </div>
            
            <div class="card">
                <h3>🎯 Theme Exposure</h3>
                <div class="metric">
                    <span class="label">Majors (BTC/ETH):</span>
                    <span class="value">{status['exposure']['by_theme']['majors']:.1f} bps</span>
                </div>
                <div class="metric">
                    <span class="label">L1s (SOL/AVAX/DOT):</span>
                    <span class="value">{status['exposure']['by_theme']['L1s']:.1f} bps</span>
                </div>
                <div class="metric">
                    <span class="label">Alts (Other):</span>
                    <span class="value">{status['exposure']['by_theme']['alts']:.1f} bps</span>
                </div>
                <div class="metric">
                    <span class="label">Total Exposure:</span>
                    <span class="value">{status['exposure']['total_bps']:.1f} bps</span>
                </div>
            </div>
            
            <div class="card">
                <h3>🤖 Bandit Learning</h3>
                <div class="metric">
                    <span class="label">Status:</span>
                    <span class="value {'active' if status['bandits']['active'] else 'inactive'}">
                        {'ACTIVE' if status['bandits']['active'] else 'OFF'}
                    </span>
                </div>
                <div class="metric">
                    <span class="label">Learning Rate (α):</span>
                    <span class="value">{status['bandits']['alpha']:.2f}</span>
                </div>
                <div class="metric">
                    <span class="label">Symbols Tracked:</span>
                    <span class="value">{status['bandits']['symbols_tracked']}</span>
                </div>
            </div>
        </div>
        
        <div class="card">
            <h3>📈 Capital Ramp Progress</h3>
            <div class="metric">
                <span class="label">Current Stage:</span>
                <span class="value">{status['ramp']['current_stage']}/{status['ramp']['total_stages']}</span>
            </div>
            <div class="metric">
                <span class="label">Stage Note:</span>
                <span class="value">{status['ramp']['stage_note']}</span>
            </div>
            <div class="metric">
                <span class="label">Leverage Cap:</span>
                <span class="value">{status['ramp']['current_leverage_cap']:.1f}x</span>
            </div>
            <div class="metric">
                <span class="label">Status:</span>
                <span class="value {'paused' if status['ramp']['paused'] else 'active'}">
                    {'PAUSED' if status['ramp']['paused'] else 'ADVANCING'}
                </span>
            </div>
            {('<div class="metric"><span class="label">Pause Reason:</span><span class="value">' + status['ramp']['pause_reason'] + '</span></div>') if status['ramp'].get('pause_reason') else ''}
            <div class="metric">
                <span class="label">Stage Progress:</span>
                <span class="value">{status['ramp']['stage_elapsed_hours']:.1f}h / {status['ramp']['stage_duration_hours']}h</span>
            </div>
            <div class="progress-bar">
                <div class="progress-fill" style="width: {status['ramp']['stage_progress_pct']:.0f}%;"></div>
            </div>
            <div class="metric">
                <span class="label">Total Ramp Time:</span>
                <span class="value">{status['ramp']['total_ramp_hours']:.1f}h</span>
            </div>
        </div>
        
        <p style="text-align: center; color: #666; margin-top: 30px;">
            Phase 3 Dashboard | Auto-refresh 30s | Edge compounding through adaptive learning
        </p>
    </div>
</body>
</html>
        """
        
        return html
        
    except Exception as e:
        return f"<html><body><h1>Error loading Phase 3 dashboard</h1><p>{str(e)}</p></body></html>"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)


@app.route("/api/phase92/status")
def api_phase92_status():
    """API: Phase 9.2 Profit Discipline status"""
    try:
        from src.phase92_profit_discipline import get_phase92_status
        status = get_phase92_status()
        return jsonify(status)
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/phase92")
def phase92_dashboard():
    """Phase 9.2 Profit Discipline Dashboard"""
    try:
        from src.phase92_profit_discipline import get_phase92_status
        status = get_phase92_status()
        
        ramps_frozen = status.get("ramps_frozen", False)
        win_rate = status.get("global_win_rate", 0)
        config = status.get("config", {})
        
        freeze_color = "#ff4466" if ramps_frozen else "#00ff88"
        winrate_color = "#ff4466" if win_rate < 40 else ("#ffa500" if win_rate < 60 else "#00ff88")
        
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Phase 9.2 Profit Discipline</title>
    <meta http-equiv="refresh" content="30">
    <style>
        body {{ font-family: monospace; background: #0a0a0a; color: #e0e0e0; padding: 20px; }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        .header {{ border-bottom: 2px solid #00ff00; padding-bottom: 10px; margin-bottom: 20px; }}
        .nav {{ margin-bottom: 20px; }}
        .nav a {{ color: #00ff00; text-decoration: none; padding: 10px 20px; background: #1a1a1a; border-radius: 5px; margin-right: 10px; }}
        .nav a:hover {{ background: #2a2a2a; }}
        .alert {{ background: #ff446633; border: 2px solid #ff4466; padding: 15px; border-radius: 10px; margin-bottom: 20px; }}
        .success {{ background: #00ff8833; border: 2px solid #00ff88; padding: 15px; border-radius: 10px; margin-bottom: 20px; }}
        .card {{ background: #1a1a1a; border: 1px solid #333; padding: 20px; border-radius: 10px; margin-bottom: 20px; }}
        .metric-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; margin-bottom: 20px; }}
        .metric-box {{ background: #1a1a1a; border: 1px solid #333; padding: 15px; border-radius: 5px; }}
        .metric-label {{ color: #888; font-size: 0.9em; }}
        .metric-value {{ font-size: 1.8em; font-weight: bold; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #333; }}
        th {{ color: #00ff00; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📊 Phase 9.2 Profit Discipline Pack</h1>
            <p>Enforcing profitability discipline over Phase 9.1 governance</p>
        </div>
        
        <div class="nav">
            <a href="/">← Back</a>
            <a href="/phase91">← Phase 9.1</a>
            <a href="/api/phase92/status">API Status</a>
        </div>
        
        {'<div class="alert"><strong>🚨 RAMPS FROZEN</strong><br>Capital ramps frozen due to low win rate. System will resume scaling when win rate recovers above ' + str(config.get('min_win_rate_pct', 40)) + '%.</div>' if ramps_frozen else '<div class="success"><strong>✅ RAMPS ACTIVE</strong><br>Win rate is healthy. Capital scaling enabled.</div>'}
        
        <div class="metric-grid">
            <div class="metric-box">
                <div class="metric-label">Global Win Rate</div>
                <div class="metric-value" style="color: {winrate_color};">{win_rate:.1f}%</div>
                <div class="metric-label">Target: {config.get('target_win_rate_pct', 60)}%+</div>
            </div>
            
            <div class="metric-box">
                <div class="metric-label">Ramp Status</div>
                <div class="metric-value" style="color: {freeze_color};">{'FROZEN' if ramps_frozen else 'ACTIVE'}</div>
                <div class="metric-label">Min threshold: {config.get('min_win_rate_pct', 40)}%</div>
            </div>
            
            <div class="metric-box">
                <div class="metric-label">Frequency Blocks</div>
                <div class="metric-value" style="color: #ffa500;">{status.get('frequency_blocks', 0)}</div>
                <div class="metric-label">Max {config.get('max_trades_per_4h', 10)} trades/4h</div>
            </div>
        </div>
        
        <div class="card">
            <h2>📋 Active Discipline Controls</h2>
            <table>
                <tr>
                    <th>Control</th>
                    <th>Threshold</th>
                    <th>Action</th>
                </tr>
                <tr>
                    <td>MTF Confidence</td>
                    <td>≥{config.get('mtf_confidence_min', 0.5)*100:.0f}%</td>
                    <td>Reject signals below threshold</td>
                </tr>
                <tr>
                    <td>Volume Boost</td>
                    <td>≥{config.get('volume_boost_min', 1.25)}x</td>
                    <td>Validate breakout strength</td>
                </tr>
                <tr>
                    <td>ROI Projection</td>
                    <td>≥{config.get('min_roi_projection_pct', 0.25)}%</td>
                    <td>Minimum expected return</td>
                </tr>
                <tr>
                    <td>Losing Streak</td>
                    <td>≥{config.get('losing_streak_threshold', 5)} losses</td>
                    <td>Reduce size by {config.get('reduce_size_pct_on_streak', 0.3)*100:.0f}%</td>
                </tr>
                <tr>
                    <td>Low Win Rate</td>
                    <td>&lt;{config.get('min_win_rate_pct', 40)}%</td>
                    <td>Reduce size by 50%</td>
                </tr>
                <tr>
                    <td>Position Exposure</td>
                    <td>≤{config.get('max_symbol_exposure_pct', 0.1)*100:.0f}% per symbol</td>
                    <td>Cap position size</td>
                </tr>
                <tr>
                    <td>Trade Frequency</td>
                    <td>{config.get('max_trades_per_4h', 10)} max/4h</td>
                    <td>Block excessive trading</td>
                </tr>
                <tr>
                    <td>Sentiment Fusion Throttle</td>
                    <td>1 trade/{config.get('sentiment_fusion_throttle_min', 60)}min per symbol</td>
                    <td>Prevent overtrading</td>
                </tr>
            </table>
        </div>
        
        <div class="card">
            <h2>🚫 Entry Rejections by Strategy</h2>
            <table>
                <tr>
                    <th>Strategy</th>
                    <th>Rejected Signals</th>
                </tr>
                {"".join([f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in status.get('entry_rejections', {}).items()]) or "<tr><td colspan='2'>No rejections yet</td></tr>"}
            </table>
        </div>
        
        <div class="card">
            <h2>⚙️ Exit Optimization Rules</h2>
            <ul style="line-height: 1.8;">
                <li><strong>Tighter Trailing Stops:</strong> {config.get('tighten_trailing_stop_atr', 1.5)}x ATR (vs default 2.0x)</li>
                <li><strong>Time-Based Exits:</strong> Close stagnant positions after {config.get('time_exit_hours', 6)} hours with &lt;0.1% gain</li>
                <li><strong>Profit Locks:</strong> Reduce size by {config.get('profit_lock_reduce_pct', 0.25)*100:.0f}% when unrealized gain ≥{config.get('profit_lock_trigger_pct', 0.5)}%</li>
            </ul>
        </div>
    </div>
</body>
</html>
        """
        return html
    except Exception as e:
        import traceback
        return f"<pre>Error: {str(e)}\n\n{traceback.format_exc()}</pre>", 500


@app.route("/api/phase93/status")
def api_phase93_status():
    """API: Phase 9.3 Venue Governance status"""
    try:
        from src.phase93_venue_governance import get_phase93_status
        status = get_phase93_status()
        return jsonify(status)
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/phase93")
def phase93_dashboard():
    """Phase 9.3 Venue Governance & Scaling Controller Dashboard"""
    try:
        from src.phase93_venue_governance import get_phase93_status
        status = get_phase93_status()
        
        spot_enabled = status.get("spot_enabled", False)
        futures_enabled = status.get("futures_enabled", True)
        spot_passes = status.get("spot_unfreeze_passes", 0)
        spot_required = status.get("spot_unfreeze_required", 5)
        
        spot_sharpe = status.get("spot_sharpe_24h", 0)
        spot_pnl = status.get("spot_pnl_24h", 0)
        futures_sharpe = status.get("futures_sharpe_24h", 0)
        futures_pnl = status.get("futures_pnl_24h", 0)
        
        venue_exp = status.get("venue_exposure", {})
        spot_exp = venue_exp.get("spot", {})
        futures_exp = venue_exp.get("futures", {})
        
        spot_color = "#00ff88" if spot_enabled else "#ff4466"
        futures_color = "#00ff88" if futures_enabled else "#ff4466"
        
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Phase 9.3 Venue Governance</title>
    <meta http-equiv="refresh" content="30">
    <style>
        body {{ font-family: monospace; background: #0a0a0a; color: #e0e0e0; padding: 20px; }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        .header {{ border-bottom: 2px solid #00ff00; padding-bottom: 10px; margin-bottom: 20px; }}
        .nav {{ margin-bottom: 20px; }}
        .nav a {{ color: #00ff00; text-decoration: none; padding: 10px 20px; background: #1a1a1a; border-radius: 5px; margin-right: 10px; }}
        .nav a:hover {{ background: #2a2a2a; }}
        .alert {{ background: #ff446633; border: 2px solid #ff4466; padding: 15px; border-radius: 10px; margin-bottom: 20px; }}
        .success {{ background: #00ff8833; border: 2px solid #00ff88; padding: 15px; border-radius: 10px; margin-bottom: 20px; }}
        .warning {{ background: #ffa50033; border: 2px solid #ffa500; padding: 15px; border-radius: 10px; margin-bottom: 20px; }}
        .card {{ background: #1a1a1a; border: 1px solid #333; padding: 20px; border-radius: 10px; margin-bottom: 20px; }}
        .metric-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 15px; margin-bottom: 20px; }}
        .metric-box {{ background: #1a1a1a; border: 1px solid #333; padding: 15px; border-radius: 5px; }}
        .metric-label {{ color: #888; font-size: 0.9em; }}
        .metric-value {{ font-size: 1.8em; font-weight: bold; }}
        .progress-bar {{ background: #222; height: 20px; border-radius: 10px; margin-top: 10px; overflow: hidden; }}
        .progress-fill {{ height: 100%; background: linear-gradient(90deg, #00ff88, #00cc66); transition: width 0.3s; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #333; }}
        th {{ color: #00ff00; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎯 Phase 9.3 Venue Governance & Scaling Controller</h1>
            <p>Prioritizing futures, gating spot until expectancy proven</p>
        </div>
        
        <div class="nav">
            <a href="/">← Back</a>
            <a href="/phase92">← Phase 9.2</a>
            <a href="/api/phase93/status">API Status</a>
        </div>
        
        {'<div class="alert"><strong>🚫 SPOT DISABLED</strong><br>Spot trading is currently disabled. Awaiting sustained expectancy: ' + str(spot_passes) + '/' + str(spot_required) + ' passes (Sharpe≥0.8, P&L≥$100).</div>' if not spot_enabled else '<div class="success"><strong>✅ SPOT ENABLED</strong><br>Spot trading has met expectancy thresholds and is now active.</div>'}
        
        <div class="card">
            <h2>🏪 Venue Status</h2>
            <div class="metric-grid">
                <div class="metric-box">
                    <div class="metric-label">Spot Trading</div>
                    <div class="metric-value" style="color: {spot_color};">{'ENABLED' if spot_enabled else 'DISABLED'}</div>
                    <div class="metric-label">24h Sharpe: {spot_sharpe:.2f} | P&L: ${spot_pnl:.2f}</div>
                </div>
                
                <div class="metric-box">
                    <div class="metric-label">Futures Trading</div>
                    <div class="metric-value" style="color: {futures_color};">{'ENABLED' if futures_enabled else 'DISABLED'}</div>
                    <div class="metric-label">24h Sharpe: {futures_sharpe:.2f} | P&L: ${futures_pnl:.2f}</div>
                </div>
            </div>
        </div>
        
        <div class="card">
            <h2>📊 Spot Unfreeze Progress</h2>
            <p>Sustained passes required: {spot_passes}/{spot_required}</p>
            <div class="progress-bar">
                <div class="progress-fill" style="width: {min(100, (spot_passes / spot_required) * 100):.0f}%;"></div>
            </div>
            <p style="margin-top: 10px; color: #888;">
                Requirements: Sharpe ≥ 0.8 AND Net P&L ≥ $100 (24h rolling)
            </p>
        </div>
        
        <div class="card">
            <h2>💰 Exposure Management</h2>
            <table>
                <tr>
                    <th>Venue</th>
                    <th>Current Exposure</th>
                    <th>Cap</th>
                    <th>Value (USD)</th>
                    <th>Status</th>
                </tr>
                <tr>
                    <td>Spot</td>
                    <td>{spot_exp.get('pct', 0)*100:.1f}%</td>
                    <td>{spot_exp.get('cap', 0)*100:.1f}%</td>
                    <td>${spot_exp.get('value_usd', 0):.2f}</td>
                    <td style="color: {'#ff4466' if spot_exp.get('pct', 0) > spot_exp.get('cap', 0) else '#00ff88'};">
                        {'BREACH' if spot_exp.get('pct', 0) > spot_exp.get('cap', 0) else 'OK'}
                    </td>
                </tr>
                <tr>
                    <td>Futures</td>
                    <td>{futures_exp.get('pct', 0)*100:.1f}%</td>
                    <td>{futures_exp.get('cap', 0)*100:.1f}%</td>
                    <td>${futures_exp.get('value_usd', 0):.2f}</td>
                    <td style="color: {'#ff4466' if futures_exp.get('pct', 0) > futures_exp.get('cap', 0) else '#00ff88'};">
                        {'BREACH' if futures_exp.get('pct', 0) > futures_exp.get('cap', 0) else 'OK'}
                    </td>
                </tr>
            </table>
        </div>
        
        <div class="card">
            <h2>⚙️ Governance Configuration</h2>
            <table>
                <tr>
                    <th>Control</th>
                    <th>Value</th>
                </tr>
                <tr>
                    <td>Max Position vs Portfolio</td>
                    <td>{status.get('config', {}).get('max_position_vs_portfolio_pct', 0.5)*100:.0f}%</td>
                </tr>
                <tr>
                    <td>Symbol Exposure Cap</td>
                    <td>{status.get('config', {}).get('symbol_exposure_cap_pct', 0.1)*100:.0f}%</td>
                </tr>
                <tr>
                    <td>Spot Max Trades/4h</td>
                    <td>{status.get('config', {}).get('max_trades_per_4h_spot', 4)}</td>
                </tr>
                <tr>
                    <td>Futures Max Trades/4h</td>
                    <td>{status.get('config', {}).get('max_trades_per_4h_futures', 12)}</td>
                </tr>
                <tr>
                    <td>Losing Streak Threshold</td>
                    <td>{status.get('config', {}).get('losing_streak_threshold', 5)} losses</td>
                </tr>
                <tr>
                    <td>Size Reduction on Streak</td>
                    <td>{status.get('config', {}).get('reduce_size_pct_on_streak', 0.3)*100:.0f}%</td>
                </tr>
            </table>
        </div>
        
        <div class="card">
            <h2>🚫 Active Blocks</h2>
            <p><strong>Blocked Symbols:</strong> {', '.join(status.get('symbol_blocks', [])) or 'None'}</p>
        </div>
    </div>
</body>
</html>
        """
        return html
    except Exception as e:
        import traceback
        return f"<pre>Error: {str(e)}\n\n{traceback.format_exc()}</pre>", 500

@app.route("/api/phase94/status")
def api_phase94_status():
    """API: Phase 9.4 Recovery & Scaling status"""
    try:
        from src.phase94_recovery_scaling import get_phase94_status
        status = get_phase94_status()
        return jsonify(status)
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/phase94")
def phase94_dashboard():
    """Phase 9.4 Recovery & Scaling Pack Dashboard"""
    try:
        from src.phase94_recovery_scaling import get_phase94_status, CFG94
        from datetime import datetime
        status = get_phase94_status()
        
        sustained_passes = status.get("sustained_passes", 0)
        passes_required = status.get("passes_required", 3)
        ramps_frozen = status.get("ramps_frozen", True)
        scaling_level = status.get("scaling_level", "none")
        ramp_mult = status.get("current_ramp_multiplier", 0.0)
        
        metrics = status.get("metrics", {})
        win_rate = metrics.get("win_rate", 0.0)
        sharpe = metrics.get("sharpe", 0.0)
        pnl = metrics.get("pnl", 0.0)
        
        thresholds = status.get("thresholds", {})
        partial = thresholds.get("partial", {})
        full = thresholds.get("full", {})
        
        exposure_caps = status.get("exposure_caps", {})
        spot_cap = exposure_caps.get("spot", 0.20)
        futures_cap = exposure_caps.get("futures", 0.60)
        
        recent_adjustments = status.get("recent_adjustments", [])
        
        ramp_color = "#ff4466" if ramps_frozen else "#00ff88"
        scaling_color = {
            "none": "#888888",
            "partial": "#ffa500",
            "full": "#00ff88"
        }.get(scaling_level, "#888888")
        
        progress_pct = min(100, (sustained_passes / passes_required) * 100)
        
        partial_met = (win_rate >= partial.get("win_rate", 0.40) and 
                      sharpe >= partial.get("sharpe", 0.80) and 
                      pnl >= partial.get("pnl", 250))
        full_met = (win_rate >= full.get("win_rate", 0.60) and 
                   sharpe >= full.get("sharpe", 1.00) and 
                   pnl >= full.get("pnl", 250))
        
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Phase 9.4 Recovery & Scaling</title>
    <meta http-equiv="refresh" content="30">
    <style>
        body {{ font-family: monospace; background: #0a0a0a; color: #e0e0e0; padding: 20px; }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        .header {{ border-bottom: 2px solid #00ff00; padding-bottom: 10px; margin-bottom: 20px; }}
        .nav {{ margin-bottom: 20px; }}
        .nav a {{ color: #00ff00; text-decoration: none; padding: 10px 20px; background: #1a1a1a; border-radius: 5px; margin-right: 10px; }}
        .nav a:hover {{ background: #2a2a2a; }}
        .alert {{ background: #ff446633; border: 2px solid #ff4466; padding: 15px; border-radius: 10px; margin-bottom: 20px; }}
        .success {{ background: #00ff8833; border: 2px solid #00ff88; padding: 15px; border-radius: 10px; margin-bottom: 20px; }}
        .warning {{ background: #ffa50033; border: 2px solid #ffa500; padding: 15px; border-radius: 10px; margin-bottom: 20px; }}
        .card {{ background: #1a1a1a; border: 1px solid #333; padding: 20px; border-radius: 10px; margin-bottom: 20px; }}
        .metric-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; margin-bottom: 20px; }}
        .metric-box {{ background: #1a1a1a; border: 1px solid #333; padding: 15px; border-radius: 5px; }}
        .metric-label {{ color: #888; font-size: 0.9em; }}
        .metric-value {{ font-size: 1.8em; font-weight: bold; }}
        .progress-bar {{ background: #333; height: 30px; border-radius: 5px; overflow: hidden; margin: 10px 0; }}
        .progress-fill {{ background: linear-gradient(90deg, #00ff88, #00aa55); height: 100%; transition: width 0.3s; }}
        .table {{ width: 100%; border-collapse: collapse; }}
        .table th, .table td {{ padding: 10px; text-align: left; border-bottom: 1px solid #333; }}
        .table th {{ color: #888; font-weight: normal; }}
        .status-badge {{ display: inline-block; padding: 5px 15px; border-radius: 5px; font-weight: bold; }}
        .check {{ color: #00ff88; }}
        .cross {{ color: #ff4466; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🚀 Phase 9.4 — Recovery & Scaling Pack</h1>
            <p>Automatically scale exposure caps and ramp sizes based on performance recovery</p>
        </div>
        
        <div class="nav">
            <a href="/">← Main Dashboard</a>
            <a href="/phase92">Phase 9.2</a>
            <a href="/phase93">Phase 9.3</a>
            <a href="/phase94">Phase 9.4</a>
        </div>
        
        {"<div class='alert'>⚠️ <strong>RAMPS FROZEN</strong> - Performance below thresholds</div>" if ramps_frozen else "<div class='success'>✅ <strong>RAMPS ACTIVE</strong> - Performance recovery detected</div>"}
        
        <div class="card">
            <h2>📊 Recovery Progress</h2>
            <p><strong>Sustained Passes:</strong> {sustained_passes} / {passes_required}</p>
            <div class="progress-bar">
                <div class="progress-fill" style="width: {progress_pct:.0f}%"></div>
            </div>
            <p><strong>Scaling Level:</strong> <span class="status-badge" style="background: {scaling_color};">{scaling_level.upper()}</span></p>
            <p><strong>Current Ramp Multiplier:</strong> <span style="color: {ramp_color};">{ramp_mult:.1f}x</span></p>
        </div>
        
        <div class="card">
            <h2>📈 Current Performance Metrics</h2>
            <div class="metric-grid">
                <div class="metric-box">
                    <div class="metric-label">Win Rate</div>
                    <div class="metric-value" style="color: {'#00ff88' if win_rate >= 0.40 else '#ff4466'};">{win_rate*100:.1f}%</div>
                </div>
                <div class="metric-box">
                    <div class="metric-label">Sharpe Ratio (24h)</div>
                    <div class="metric-value" style="color: {'#00ff88' if sharpe >= 0.80 else '#ff4466'};">{sharpe:.2f}</div>
                </div>
                <div class="metric-box">
                    <div class="metric-label">Net P&L (24h)</div>
                    <div class="metric-value" style="color: {'#00ff88' if pnl >= 250 else '#ff4466'};">${pnl:.2f}</div>
                </div>
            </div>
        </div>
        
        <div class="card">
            <h2>🎯 Recovery Thresholds</h2>
            <table class="table">
                <tr>
                    <th>Metric</th>
                    <th>Partial Recovery</th>
                    <th>Full Recovery</th>
                    <th>Current</th>
                    <th>Status</th>
                </tr>
                <tr>
                    <td>Win Rate</td>
                    <td>{partial.get('win_rate', 0.40)*100:.0f}%</td>
                    <td>{full.get('win_rate', 0.60)*100:.0f}%</td>
                    <td>{win_rate*100:.1f}%</td>
                    <td>{'<span class="check">✓</span>' if partial_met else '<span class="cross">✗</span>'}</td>
                </tr>
                <tr>
                    <td>Sharpe Ratio</td>
                    <td>{partial.get('sharpe', 0.80):.2f}</td>
                    <td>{full.get('sharpe', 1.00):.2f}</td>
                    <td>{sharpe:.2f}</td>
                    <td>{'<span class="check">✓</span>' if sharpe >= partial.get('sharpe', 0.80) else '<span class="cross">✗</span>'}</td>
                </tr>
                <tr>
                    <td>Net P&L (24h)</td>
                    <td>${partial.get('pnl', 250):.0f}</td>
                    <td>${full.get('pnl', 250):.0f}</td>
                    <td>${pnl:.2f}</td>
                    <td>{'<span class="check">✓</span>' if pnl >= 250 else '<span class="cross">✗</span>'}</td>
                </tr>
            </table>
        </div>
        
        <div class="card">
            <h2>📊 Current Exposure Caps</h2>
            <table class="table">
                <tr>
                    <th>Venue</th>
                    <th>Current Cap</th>
                    <th>Increment (Partial)</th>
                    <th>Increment (Full)</th>
                </tr>
                <tr>
                    <td>Spot</td>
                    <td>{spot_cap*100:.0f}%</td>
                    <td>+{CFG94.exposure_increment_partial*100:.0f}%</td>
                    <td>+{CFG94.exposure_increment_full*100:.0f}%</td>
                </tr>
                <tr>
                    <td>Futures</td>
                    <td>{futures_cap*100:.0f}%</td>
                    <td>+{CFG94.exposure_increment_partial*100:.0f}%</td>
                    <td>+{CFG94.exposure_increment_full*100:.0f}%</td>
                </tr>
            </table>
        </div>
        
        {"<div class='card'><h2>📜 Recent Exposure Adjustments</h2>" + ("<table class='table'><tr><th>Timestamp</th><th>Increment</th><th>Spot Cap</th><th>Futures Cap</th></tr>" + "".join([f"<tr><td>{datetime.fromtimestamp(adj.get('ts', 0)).strftime('%Y-%m-%d %H:%M:%S')}</td><td>+{adj.get('increment', 0)*100:.0f}%</td><td>{adj.get('spot_cap', 0)*100:.0f}%</td><td>{adj.get('futures_cap', 0)*100:.0f}%</td></tr>" for adj in recent_adjustments]) + "</table>" if recent_adjustments else "<p>No adjustments yet</p>") + "</div>"}
        
        <div class="card">
            <h2>⚙️ Configuration</h2>
            <table class="table">
                <tr>
                    <td>Sustained Passes Required</td>
                    <td>{CFG94.sustained_passes_required}</td>
                </tr>
                <tr>
                    <td>Check Cadence</td>
                    <td>{CFG94.cadence_sec} seconds</td>
                </tr>
                <tr>
                    <td>Partial Ramp Multiplier</td>
                    <td>{CFG94.ramp_multiplier_partial:.1f}x</td>
                </tr>
                <tr>
                    <td>Full Ramp Multiplier</td>
                    <td>{CFG94.ramp_multiplier_full:.1f}x</td>
                </tr>
            </table>
        </div>
    </div>
</body>
</html>
        """
        return html
    except Exception as e:
        import traceback
        return f"<pre>Error: {str(e)}\n\n{traceback.format_exc()}</pre>", 500

@app.route("/api/phase10/status")
def api_phase10_status():
    """API: Phase 10 Profit Engine status"""
    try:
        from src.phase10_profit_engine import get_phase10_status
        status = get_phase10_status()
        return jsonify(status)
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/phase10")
def phase10_dashboard():
    """Phase 10 Profit Engine Dashboard"""
    try:
        from src.phase10_profit_engine import get_phase10_status
        status = get_phase10_status()
        
        profit_gates = status.get("profit_gates", {})
        gates_passed = profit_gates.get("all_gates_passed", False)
        gate_details = profit_gates.get("details", [])
        
        metrics = status.get("metrics", {})
        win_rate = metrics.get("global_win_rate", 0.0)
        sharpe = metrics.get("global_sharpe", 0.0)
        pnl = metrics.get("session_pnl", 0.0)
        
        trade_stats = status.get("trade_stats", {})
        trades_executed = trade_stats.get("trades_executed", 0)
        trades_blocked = trade_stats.get("trades_blocked", 0)
        total_trades = trades_executed + trades_blocked
        execution_rate = (trades_executed / total_trades * 100) if total_trades > 0 else 0
        
        loss_protection = status.get("loss_protection", {})
        session_loss_pct = loss_protection.get("session_loss_pct", 0.0)
        daily_loss_pct = loss_protection.get("daily_loss_pct", 0.0)
        session_frozen = loss_protection.get("session_frozen", False)
        daily_frozen = loss_protection.get("daily_frozen", False)
        
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Phase 10 Profit Engine</title>
    <meta http-equiv="refresh" content="30">
    <style>
        body {{ font-family: monospace; background: #0a0a0a; color: #e0e0e0; padding: 20px; }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        .header {{ border-bottom: 2px solid #ffd700; padding-bottom: 10px; margin-bottom: 20px; }}
        .nav {{ margin-bottom: 20px; }}
        .nav a {{ color: #ffd700; text-decoration: none; padding: 10px 20px; background: #1a1a1a; border-radius: 5px; margin-right: 10px; }}
        .nav a:hover {{ background: #2a2a2a; }}
        .alert {{ background: #ff446633; border: 2px solid #ff4466; padding: 15px; border-radius: 10px; margin-bottom: 20px; }}
        .success {{ background: #ffd70033; border: 2px solid #ffd700; padding: 15px; border-radius: 10px; margin-bottom: 20px; }}
        .card {{ background: #1a1a1a; border: 1px solid #333; padding: 20px; border-radius: 10px; margin-bottom: 20px; }}
        .metric-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; margin-bottom: 20px; }}
        .metric-box {{ background: #1a1a1a; border: 1px solid #333; padding: 15px; border-radius: 5px; }}
        .metric-label {{ color: #888; font-size: 0.9em; }}
        .metric-value {{ font-size: 1.8em; font-weight: bold; }}
        .table {{ width: 100%; border-collapse: collapse; }}
        .table th, .table td {{ padding: 10px; text-align: left; border-bottom: 1px solid #333; }}
        .table th {{ color: #888; font-weight: normal; }}
        .status-badge {{ display: inline-block; padding: 5px 15px; border-radius: 5px; font-weight: bold; }}
        .check {{ color: #00ff88; }}
        .cross {{ color: #ff4466; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>💰 Phase 10 — Profit Engine</h1>
            <p>Profit-first execution layer with expectancy gates, regime routing, and loss protection</p>
        </div>
        
        <div class="nav">
            <a href="/">← Main Dashboard</a>
            <a href="/phase92">Phase 9.2</a>
            <a href="/phase93">Phase 9.3</a>
            <a href="/phase94">Phase 9.4</a>
            <a href="/phase10">Phase 10</a>
        </div>
        
        {"<div class='success'>✅ <strong>PROFIT GATES PASSED</strong> - All expectancy thresholds met</div>" if gates_passed else "<div class='alert'>⚠️ <strong>PROFIT GATES FAILED</strong> - Expectancy thresholds not met</div>"}
        
        <div class="card">
            <h2>📊 Global Metrics</h2>
            <div class="metric-grid">
                <div class="metric-box">
                    <div class="metric-label">Global Win Rate</div>
                    <div class="metric-value" style="color: {'#00ff88' if win_rate >= 0.45 else '#ff4466'};">{win_rate*100:.1f}%</div>
                </div>
                <div class="metric-box">
                    <div class="metric-label">Global Sharpe (24h)</div>
                    <div class="metric-value" style="color: {'#00ff88' if sharpe >= 0.5 else '#ff4466'};">{sharpe:.2f}</div>
                </div>
                <div class="metric-box">
                    <div class="metric-label">Session P&L</div>
                    <div class="metric-value" style="color: {'#00ff88' if pnl >= 0 else '#ff4466'};">${pnl:.2f}</div>
                </div>
            </div>
        </div>
        
        <div class="card">
            <h2>🎯 Profit Gates Status</h2>
            <table class="table">
                <tr>
                    <th>Gate</th>
                    <th>Status</th>
                    <th>Details</th>
                </tr>
                {''.join([f"<tr><td>{g.get('name', 'Unknown')}</td><td><span class='{'check' if g.get('passed', False) else 'cross'}'>{'✓' if g.get('passed', False) else '✗'}</span></td><td>{g.get('reason', 'N/A')}</td></tr>" for g in gate_details])}
            </table>
        </div>
        
        <div class="card">
            <h2>📈 Trade Execution Stats</h2>
            <table class="table">
                <tr>
                    <th>Metric</th>
                    <th>Value</th>
                </tr>
                <tr>
                    <td>Trades Executed</td>
                    <td style="color: #00ff88;">{trades_executed}</td>
                </tr>
                <tr>
                    <td>Trades Blocked</td>
                    <td style="color: #ff4466;">{trades_blocked}</td>
                </tr>
                <tr>
                    <td>Execution Rate</td>
                    <td style="color: {'#00ff88' if execution_rate >= 50 else '#ff4466'};">{execution_rate:.1f}%</td>
                </tr>
            </table>
        </div>
        
        <div class="card">
            <h2>🛡️ Loss Protection</h2>
            <table class="table">
                <tr>
                    <th>Protection Type</th>
                    <th>Loss %</th>
                    <th>Status</th>
                </tr>
                <tr>
                    <td>Session Loss Limit</td>
                    <td>{session_loss_pct:.2f}%</td>
                    <td>{"<span class='cross'>FROZEN</span>" if session_frozen else "<span class='check'>ACTIVE</span>"}</td>
                </tr>
                <tr>
                    <td>Daily Loss Limit</td>
                    <td>{daily_loss_pct:.2f}%</td>
                    <td>{"<span class='cross'>FROZEN</span>" if daily_frozen else "<span class='check'>ACTIVE</span>"}</td>
                </tr>
            </table>
        </div>
    </div>
</body>
</html>
        """
        return html
    except Exception as e:
        import traceback
        return f"<pre>Error: {str(e)}\n\n{traceback.format_exc()}</pre>", 500

@app.route("/api/phase101/status")
def api_phase101_status():
    """API: Phase 10.1 Attribution Allocator status"""
    try:
        from src.phase101_allocator import get_attribution_scores, get_breach_stats
        return jsonify({
            "attribution": get_attribution_scores(),
            "breach_stats": get_breach_stats()
        })
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/phase101")
def phase101_dashboard():
    """Phase 10.1 Attribution-Weighted Allocator Dashboard"""
    try:
        from src.phase101_allocator import get_attribution_scores, get_breach_stats
        
        scores = get_attribution_scores()
        breach_stats = get_breach_stats()
        
        spot_scores = scores.get("spot", {})
        futures_scores = scores.get("futures", {})
        strategy_scores = scores.get("strategy", {})
        
        breach_alert_html = ""
        if breach_stats["alert_active"]:
            breach_alert_html = f"""<div class='alert'>🚨 <strong>BREACH ALERT</strong> - {breach_stats['recent_24h']} spot execution attempts in 24h (threshold: {breach_stats['threshold']})</div>"""
        
        spot_rows = ""
        if spot_scores:
            for symbol, score in sorted(spot_scores.items(), key=lambda x: x[1], reverse=True):
                color = "#00ff88" if score > 1.0 else ("#ff4466" if score < 1.0 else "#888")
                multiplier_text = "Boost" if score > 1.0 else ("Reduce" if score < 1.0 else "Neutral")
                spot_rows += f"<tr><td>{symbol}</td><td style='color:{color}'>{score:.3f}</td><td>{multiplier_text}</td></tr>"
        else:
            spot_rows = "<tr><td colspan='3' style='color:#888;'>No spot trades yet</td></tr>"
        
        futures_rows = ""
        if futures_scores:
            for symbol, score in sorted(futures_scores.items(), key=lambda x: x[1], reverse=True):
                color = "#00ff88" if score > 1.0 else ("#ff4466" if score < 1.0 else "#888")
                multiplier_text = "Boost" if score > 1.0 else ("Reduce" if score < 1.0 else "Neutral")
                futures_rows += f"<tr><td>{symbol}</td><td style='color:{color}'>{score:.3f}</td><td>{multiplier_text}</td></tr>"
        else:
            futures_rows = "<tr><td colspan='3' style='color:#888;'>No futures trades yet</td></tr>"
        
        strategy_rows = ""
        if strategy_scores:
            for strategy, score in sorted(strategy_scores.items(), key=lambda x: x[1], reverse=True):
                color = "#00ff88" if score > 1.0 else ("#ff4466" if score < 1.0 else "#888")
                impact = "Boost" if score > 1.0 else ("Reduce" if score < 1.0 else "Neutral")
                impact_color = "#00ff88" if score > 1.0 else "#ff4466"
                strategy_rows += f"<tr><td>{strategy}</td><td style='color:{color}'>{score:.3f}</td><td style='color:{impact_color}'>{impact}</td></tr>"
        else:
            strategy_rows = "<tr><td colspan='3' style='color:#888;'>No strategy data yet</td></tr>"
        
        breach_total_color = "#ff4466" if breach_stats["total_breaches"] > 0 else "#888"
        breach_recent_color = "#ff4466" if breach_stats["recent_24h"] >= breach_stats["threshold"] else ("#ffd700" if breach_stats["recent_24h"] > 0 else "#00ff88")
        
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Phase 10.1 Attribution Allocator</title>
    <meta http-equiv="refresh" content="30">
    <style>
        body {{ font-family: monospace; background: #0a0a0a; color: #e0e0e0; padding: 20px; }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        .header {{ border-bottom: 2px solid #ff8800; padding-bottom: 10px; margin-bottom: 20px; }}
        .nav {{ margin-bottom: 20px; }}
        .nav a {{ color: #ff8800; text-decoration: none; padding: 10px 20px; background: #1a1a1a; border-radius: 5px; margin-right: 10px; }}
        .nav a:hover {{ background: #2a2a2a; }}
        .alert {{ background: #ff446633; border: 2px solid #ff4466; padding: 15px; border-radius: 10px; margin-bottom: 20px; }}
        .card {{ background: #1a1a1a; border: 1px solid #333; padding: 20px; border-radius: 10px; margin-bottom: 20px; }}
        .metric-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; margin-bottom: 20px; }}
        .metric-box {{ background: #1a1a1a; border: 1px solid #333; padding: 15px; border-radius: 5px; }}
        .metric-label {{ color: #888; font-size: 0.9em; }}
        .metric-value {{ font-size: 1.8em; font-weight: bold; }}
        .table {{ width: 100%; border-collapse: collapse; }}
        .table th, .table td {{ padding: 10px; text-align: left; border-bottom: 1px solid #333; }}
        .table th {{ color: #888; font-weight: normal; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎯 Phase 10.1 — Attribution-Weighted Allocator</h1>
            <p>Breach alerting, venue attribution scoring, and reward shaping</p>
        </div>
        
        <div class="nav">
            <a href="/">← Main Dashboard</a>
            <a href="/phase10">Phase 10</a>
            <a href="/phase101">Phase 10.1</a>
        </div>
        
        {breach_alert_html}
        
        <div class="card">
            <h2>🚨 Enforcement Breach Stats</h2>
            <div class="metric-grid">
                <div class="metric-box">
                    <div class="metric-label">Total Breaches</div>
                    <div class="metric-value" style="color: {breach_total_color};">{breach_stats["total_breaches"]}</div>
                </div>
                <div class="metric-box">
                    <div class="metric-label">Recent (24h)</div>
                    <div class="metric-value" style="color: {breach_recent_color};">{breach_stats["recent_24h"]}</div>
                </div>
                <div class="metric-box">
                    <div class="metric-label">Alert Threshold</div>
                    <div class="metric-value" style="color: #888;">{breach_stats["threshold"]}</div>
                </div>
            </div>
        </div>
        
        <div class="card">
            <h2>🏆 Spot Attribution Scores</h2>
            <table class="table">
                <tr>
                    <th>Symbol</th>
                    <th>Score</th>
                    <th>Allocation Multiplier</th>
                </tr>
                {spot_rows}
            </table>
        </div>
        
        <div class="card">
            <h2>🚀 Futures Attribution Scores</h2>
            <table class="table">
                <tr>
                    <th>Symbol</th>
                    <th>Score</th>
                    <th>Allocation Multiplier</th>
                </tr>
                {futures_rows}
            </table>
        </div>
        
        <div class="card">
            <h2>🎯 Strategy Attribution Scores</h2>
            <table class="table">
                <tr>
                    <th>Strategy</th>
                    <th>Score</th>
                    <th>Allocation Impact</th>
                </tr>
                {strategy_rows}
            </table>
        </div>
    </div>
</body>
</html>
        """
        return html
    except Exception as e:
        import traceback
        return f"<pre>Error: {str(e)}\n\n{traceback.format_exc()}</pre>", 500

@app.route("/api/phase102/status")
def api_phase102_status():
    """API: Phase 10.2 Futures Optimizer status"""
    try:
        from src.phase102_futures_optimizer import get_phase102_status, get_shadow_leaderboard
        return jsonify({
            "status": get_phase102_status(),
            "leaderboard": get_shadow_leaderboard()
        })
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/phase102")
def phase102_dashboard():
    """Phase 10.2 Futures Optimizer Dashboard"""
    try:
        from src.phase102_futures_optimizer import get_phase102_status, get_shadow_leaderboard
        
        status = get_phase102_status()
        leaderboard = get_shadow_leaderboard()
        
        ranked = status.get("ranked_futures", [])[:10]
        multipliers = status.get("allocation_multipliers", {})
        top_n = status.get("top_n", 3)
        
        ranked_rows = ""
        for i, (symbol, score, metrics) in enumerate(ranked):
            mult = multipliers.get(symbol, 1.0)
            elig = "✓" if metrics.get("eligible", False) else "✗"
            color = "#00ff88" if i < top_n else ("#ffd700" if metrics.get("eligible") else "#ff4466")
            boost_text = f"{mult:.2f}x" if mult != 1.0 else "base"
            ranked_rows += f"""
                <tr style='background: {"#1a2a1a" if i < top_n else "#1a1a1a"}'>
                    <td>#{i+1}</td>
                    <td style='color:{color};font-weight:bold'>{symbol}</td>
                    <td>{score:.1f}</td>
                    <td>{metrics['wr']:.1f}%</td>
                    <td>{metrics['sh']:.2f}</td>
                    <td>${metrics['pnl']:.2f}</td>
                    <td style='color:{color}'>{elig}</td>
                    <td style='color:{color};font-weight:bold'>{boost_text}</td>
                </tr>
            """
        
        leaderboard_rows = ""
        for item in leaderboard[:15]:
            cfg_id = item["cfg_id"]
            parts = cfg_id.split(":")
            symbol_strat = f"{parts[0]}/{parts[1]}" if len(parts) >= 2 else cfg_id
            color = "#00ff88" if item["wr"] >= 60 else ("#ffd700" if item["wr"] >= 50 else "#888")
            leaderboard_rows += f"""
                <tr>
                    <td style='font-size:0.85em'>{symbol_strat}</td>
                    <td style='color:{color};font-weight:bold'>{item["wr"]:.1f}%</td>
                    <td>{item["sharpe"]:.2f}</td>
                    <td style='color:{"#00ff88" if item["pnl"] > 0 else "#ff4466"}'>${item["pnl"]:.2f}</td>
                    <td>{item["samples"]}</td>
                </tr>
            """
        
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Phase 10.2 Futures Optimizer</title>
    <meta http-equiv="refresh" content="30">
    <style>
        body {{ font-family: monospace; background: #0a0a0a; color: #e0e0e0; padding: 20px; }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        .header {{ border-bottom: 2px solid #ff6600; padding-bottom: 10px; margin-bottom: 20px; }}
        .nav {{ margin-bottom: 20px; }}
        .nav a {{ color: #ff6600; text-decoration: none; padding: 10px 20px; background: #1a1a1a; border-radius: 5px; margin-right: 10px; }}
        .nav a:hover {{ background: #2a2a2a; }}
        .card {{ background: #1a1a1a; border: 1px solid #333; padding: 20px; border-radius: 10px; margin-bottom: 20px; }}
        .metric-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin-bottom: 20px; }}
        .metric-box {{ background: #1a1a1a; border: 1px solid #333; padding: 15px; border-radius: 5px; }}
        .metric-label {{ color: #888; font-size: 0.9em; }}
        .metric-value {{ font-size: 1.8em; font-weight: bold; }}
        .table {{ width: 100%; border-collapse: collapse; }}
        .table th, .table td {{ padding: 10px; text-align: left; border-bottom: 1px solid #333; }}
        .table th {{ color: #888; font-weight: normal; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🔥 Phase 10.2 — Futures Optimizer</h1>
            <p>Concentration, Shadow Sweeps, and Promotion</p>
        </div>
        
        <div class="nav">
            <a href="/">← Main Dashboard</a>
            <a href="/phase101">Phase 10.1</a>
            <a href="/phase102">Phase 10.2</a>
        </div>
        
        <div class="card">
            <h2>📊 System Status</h2>
            <div class="metric-grid">
                <div class="metric-box">
                    <div class="metric-label">Top N Concentration</div>
                    <div class="metric-value" style="color: #ff6600;">{top_n}</div>
                </div>
                <div class="metric-box">
                    <div class="metric-label">Shadow Configs</div>
                    <div class="metric-value" style="color: #ffd700;">{status.get("shadow_configs_count", 0)}</div>
                </div>
                <div class="metric-box">
                    <div class="metric-label">Shadow Results</div>
                    <div class="metric-value" style="color: #00ff88;">{status.get("shadow_results_count", 0)}</div>
                </div>
                <div class="metric-box">
                    <div class="metric-label">Live Configs</div>
                    <div class="metric-value" style="color: #88ff00;">{status.get("live_configs_count", 0)}</div>
                </div>
            </div>
        </div>
        
        <div class="card">
            <h2>🎯 Futures Symbol Rankings (Top {top_n} Concentrated)</h2>
            <table class="table">
                <tr>
                    <th>Rank</th>
                    <th>Symbol</th>
                    <th>Score</th>
                    <th>Win Rate</th>
                    <th>Sharpe</th>
                    <th>P&L 24h</th>
                    <th>Eligible</th>
                    <th>Allocation</th>
                </tr>
                {ranked_rows if ranked_rows else "<tr><td colspan='8' style='color:#888;text-align:center'>No rankings yet (waiting for data)</td></tr>"}
            </table>
        </div>
        
        <div class="card">
            <h2>🏆 Shadow Config Leaderboard</h2>
            <table class="table">
                <tr>
                    <th>Config</th>
                    <th>Win Rate</th>
                    <th>Sharpe</th>
                    <th>P&L</th>
                    <th>Samples</th>
                </tr>
                {leaderboard_rows if leaderboard_rows else "<tr><td colspan='5' style='color:#888;text-align:center'>No shadow results yet</td></tr>"}
            </table>
        </div>
    </div>
</body>
</html>
        """
        return html
    except Exception as e:
        import traceback
        return f"<pre>Error: {str(e)}\n\n{traceback.format_exc()}</pre>", 500


@app.route("/api/phase10x/status")
def api_phase10x_status():
    """API: Phase 10.3-10.5 status"""
    try:
        from src.phase10x_combined import get_phase10x_status
        return jsonify(get_phase10x_status())
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/phase10x")
def phase10x_dashboard():
    """Phase 10.3-10.5 Dashboard"""
    try:
        from src.phase10x_combined import get_phase10x_status
        status = get_phase10x_status()
        
        paused = status.get("paused_reason", "")
        regime = status.get("current_regime", "Unknown")
        exp_stats = status.get("experiments", {})
        exec_stats = status.get("exec_stats", {})
        last_ticks = status.get("last_ticks", {})
        
        top_performers = exp_stats.get("top_performers", [])
        top_rows = ""
        for p in top_performers:
            top_rows += f"""
                <tr>
                    <td>{p['cfg_id']}</td>
                    <td>{p['wr']:.1f}%</td>
                    <td>{p['sharpe']:.2f}</td>
                    <td>${p['pnl']:.2f}</td>
                    <td>{p['samples']}</td>
                </tr>
            """
        
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Phase 10.3-10.5</title>
    <meta http-equiv="refresh" content="30">
    <style>
        body {{ font-family: monospace; background: #0a0a0a; color: #e0e0e0; padding: 20px; }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        .header {{ border-bottom: 2px solid #ff6600; padding-bottom: 10px; margin-bottom: 20px; }}
        .nav {{ margin-bottom: 20px; }}
        .nav a {{ color: #ff6600; text-decoration: none; padding: 10px 20px; background: #1a1a1a; border-radius: 5px; margin-right: 10px; }}
        .card {{ background: #1a1a1a; border: 1px solid #333; padding: 20px; border-radius: 10px; margin-bottom: 20px; }}
        .metric-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin-bottom: 20px; }}
        .metric-box {{ background: #1a1a1a; border: 1px solid #333; padding: 15px; border-radius: 5px; }}
        .metric-label {{ color: #888; font-size: 0.9em; }}
        .metric-value {{ font-size: 1.8em; font-weight: bold; }}
        .table {{ width: 100%; border-collapse: collapse; }}
        .table th, .table td {{ padding: 10px; text-align: left; border-bottom: 1px solid #333; }}
        .table th {{ color: #888; font-weight: normal; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎯 Phase 10.3-10.5</h1>
            <p>Adaptive Risk + Execution + Experiments</p>
        </div>
        <div class="nav">
            <a href="/">← Main</a>
            <a href="/phase102">Phase 10.2</a>
            <a href="/phase10x">Phase 10.3-10.5</a>
        </div>
        <div class="card">
            <h2>Status</h2>
            <div class="metric-grid">
                <div class="metric-box">
                    <div class="metric-label">Regime</div>
                    <div class="metric-value">{regime}</div>
                </div>
                <div class="metric-box">
                    <div class="metric-label">Entry</div>
                    <div class="metric-value">{paused if paused else "Active"}</div>
                </div>
                <div class="metric-box">
                    <div class="metric-label">Configs</div>
                    <div class="metric-value">{exp_stats.get('total_configs', 0)}</div>
                </div>
                <div class="metric-box">
                    <div class="metric-label">Live</div>
                    <div class="metric-value">{exp_stats.get('live_configs', 0)}</div>
                </div>
            </div>
        </div>
        <div class="card">
            <h2>Experiments</h2>
            <table class="table">
                <tr>
                    <th>Config</th>
                    <th>WR</th>
                    <th>Sharpe</th>
                    <th>P&L</th>
                    <th>Samples</th>
                </tr>
                {top_rows if top_rows else "<tr><td colspan='5'>No results yet</td></tr>"}
            </table>
        </div>
    </div>
</body>
</html>
        """
        return html
    except Exception as e:
        import traceback
        return f"<pre>Error: {str(e)}\n\n{traceback.format_exc()}</pre>", 500


@app.route("/api/phase106/status")
def api_phase106_status():
    """API: Phase 10.6 Calibration status"""
    try:
        from src.phase106_calibration import get_phase106_status
        return jsonify(get_phase106_status())
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/api/phase107_109/status")
def api_phase107_109_status():
    """API: Phase 10.7-10.9 status"""
    try:
        from src.phase107_109 import get_phase107_109_status
        return jsonify(get_phase107_109_status())
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/api/phase1010_1012/status")
def api_phase1010_1012_status():
    """API: Phase 10.10-10.12 status"""
    try:
        from src.phase1010_1012 import get_phase1010_1012_status
        return jsonify(get_phase1010_1012_status())
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/phase1010_1012")
def phase1010_1012_dashboard():
    """Phase 10.10-10.12 Dashboard: Collaborative Intelligence + Arbitrage + Operator Controls"""
    try:
        from src.phase1010_1012 import get_phase1010_1012_status
        status = get_phase1010_1012_status()
        
        collab = status.get("collaborative", {})
        arb = status.get("arbitrage", {})
        oper = status.get("operator", {})
        
        bias_rows = ""
        for sym, data in sorted(collab.get("last_bias", {}).items(), key=lambda x: x[1].get("ts", 0), reverse=True)[:10]:
            mult = data.get("mult", 1.0)
            flow = data.get("flow", 0.5)
            sentiment = data.get("sentiment", 0.5)
            blocktrades = data.get("blocktrades", 0.5)
            color = "#00ff88" if mult > 1.05 else ("#ff4466" if mult < 0.95 else "#ffd700")
            bias_rows += f"""
                <tr>
                    <td><strong>{sym}</strong></td>
                    <td style='color:{color}'>{mult:.3f}x</td>
                    <td>{flow:.2f}</td>
                    <td>{sentiment:.2f}</td>
                    <td>{blocktrades:.2f}</td>
                    <td>${data.get('adjusted_size', 0):.2f}</td>
                </tr>
            """
        
        spread_rows = ""
        for sym, spread_bps in sorted(arb.get("last_spreads", {}).items(), key=lambda x: abs(x[1]), reverse=True)[:10]:
            color = "#ff4466" if abs(spread_bps) >= 15 else "#00ff88"
            spread_rows += f"""
                <tr>
                    <td><strong>{sym}</strong></td>
                    <td style='color:{color}'>{spread_bps:.1f}</td>
                    <td>{'⚠️ ARB' if abs(spread_bps) >= 15 else 'Normal'}</td>
                </tr>
            """
        
        opp_rows = ""
        for opp in arb.get("opportunities", [])[-10:]:
            opp_rows += f"""
                <tr>
                    <td><strong>{opp.get('symbol', '')}</strong></td>
                    <td>{opp.get('spread_bps', 0):.1f}</td>
                    <td>${opp.get('max_cross_usd', 0):.2f}</td>
                    <td>${opp.get('fut_mid', 0):.2f}</td>
                    <td>${opp.get('spot_mid', 0):.2f}</td>
                </tr>
            """
        
        override_rows = ""
        for override in oper.get("overrides", [])[-10:]:
            override_rows += f"""
                <tr>
                    <td><strong>{override.get('symbol', '')}</strong></td>
                    <td>{override.get('action', '')}</td>
                    <td>{str(override.get('params', {})[:50])}</td>
                </tr>
            """
        
        block_rows = ""
        for block in oper.get("active_blocks", []):
            block_rows += f"""
                <tr style='background: #2a1a1a'>
                    <td><strong>{block.get('symbol', '')}</strong></td>
                    <td>{block.get('reason', '')}</td>
                    <td>{int(block.get('end_ts', 0) - time.time())}s remaining</td>
                </tr>
            """
        
        import time
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Phase 10.10-10.12</title>
    <meta http-equiv="refresh" content="30">
    <style>
        body {{ font-family: monospace; background: #0a0a0a; color: #e0e0e0; padding: 20px; }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        .header {{ border-bottom: 2px solid #ff6600; padding-bottom: 10px; margin-bottom: 20px; }}
        .nav {{ margin-bottom: 20px; }}
        .nav a {{ color: #ff6600; text-decoration: none; padding: 10px 20px; background: #1a1a1a; border-radius: 5px; margin-right: 10px; }}
        .card {{ background: #1a1a1a; border: 1px solid #333; padding: 20px; border-radius: 10px; margin-bottom: 20px; }}
        .metric-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin-bottom: 20px; }}
        .metric-box {{ background: #1a1a1a; border: 1px solid #333; padding: 15px; border-radius: 5px; }}
        .metric-label {{ color: #888; font-size: 0.9em; }}
        .metric-value {{ font-size: 1.8em; font-weight: bold; }}
        .table {{ width: 100%; border-collapse: collapse; }}
        .table th {{ background: #222; color: #ff6600; padding: 10px; text-align: left; }}
        .table td {{ padding: 8px; border-bottom: 1px solid #333; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🌐 Phase 10.10-10.12 — Collaborative Intelligence + Arbitrage + Operator Controls</h1>
            <p style="color: #888;">External feeds, cross-venue spreads, and institutional overrides</p>
        </div>
        <div class="nav">
            <a href="/">← Main</a>
            <a href="/phase102">Phase 10.2</a>
            <a href="/phase10x">Phase 10.3-10.5</a>
            <a href="/phase106">Phase 10.6</a>
            <a href="/phase107_109">Phase 10.7-10.9</a>
            <a href="/phase1010_1012">Phase 10.10-10.12</a>
        </div>
        
        <div class="card">
            <h2>10.10 Collaborative Intelligence</h2>
            <div class="metric-grid">
                <div class="metric-box">
                    <div class="metric-label">Symbols Tracked</div>
                    <div class="metric-value" style="color: #00bfff;">{collab.get('symbols_tracked', 0)}</div>
                </div>
            </div>
            <h3>Recent External Biases</h3>
            <table class="table">
                <tr>
                    <th>Symbol</th>
                    <th>Multiplier</th>
                    <th>Flow</th>
                    <th>Sentiment</th>
                    <th>Block Trades</th>
                    <th>Adjusted Size</th>
                </tr>
                {bias_rows if bias_rows else "<tr><td colspan='6'>No biases yet</td></tr>"}
            </table>
        </div>
        
        <div class="card">
            <h2>10.11 Cross-Venue Arbitrage</h2>
            <div class="metric-grid">
                <div class="metric-box">
                    <div class="metric-label">Spreads Tracked</div>
                    <div class="metric-value" style="color: #ff6600;">{arb.get('spreads_tracked', 0)}</div>
                </div>
                <div class="metric-box">
                    <div class="metric-label">Opportunities</div>
                    <div class="metric-value" style="color: #ffd700;">{arb.get('opportunities_count', 0)}</div>
                </div>
            </div>
            <h3>Venue Spreads</h3>
            <table class="table">
                <tr>
                    <th>Symbol</th>
                    <th>Spread (bps)</th>
                    <th>Status</th>
                </tr>
                {spread_rows if spread_rows else "<tr><td colspan='3'>No spreads yet</td></tr>"}
            </table>
            <h3>Arbitrage Opportunities</h3>
            <table class="table">
                <tr>
                    <th>Symbol</th>
                    <th>Spread (bps)</th>
                    <th>Max Cross USD</th>
                    <th>Futures Mid</th>
                    <th>Spot Mid</th>
                </tr>
                {opp_rows if opp_rows else "<tr><td colspan='5'>No opportunities detected</td></tr>"}
            </table>
        </div>
        
        <div class="card">
            <h2>10.12 Operator Controls</h2>
            <div class="metric-grid">
                <div class="metric-box">
                    <div class="metric-label">Total Overrides</div>
                    <div class="metric-value" style="color: #ffd700;">{oper.get('overrides_count', 0)}</div>
                </div>
                <div class="metric-box">
                    <div class="metric-label">Active Blocks</div>
                    <div class="metric-value" style="color: {'#ff4466' if oper.get('blocks_count', 0) > 0 else '#00ff88'};">
                        {oper.get('blocks_count', 0)}
                    </div>
                </div>
            </div>
            <h3>Active Symbol Blocks</h3>
            <table class="table">
                <tr>
                    <th>Symbol</th>
                    <th>Reason</th>
                    <th>Time Remaining</th>
                </tr>
                {block_rows if block_rows else "<tr><td colspan='3'>No active blocks</td></tr>"}
            </table>
            <h3>Recent Overrides</h3>
            <table class="table">
                <tr>
                    <th>Symbol</th>
                    <th>Action</th>
                    <th>Parameters</th>
                </tr>
                {override_rows if override_rows else "<tr><td colspan='3'>No overrides yet</td></tr>"}
            </table>
        </div>
    </div>
</body>
</html>
        """
        return html
    except Exception as e:
        import traceback
        return f"<pre>Error: {{str(e)}}\n\n{{traceback.format_exc()}}</pre>", 500

@app.route("/phase107_109")
def phase107_109_dashboard():
    """Phase 10.7-10.9 Dashboard: Predictive Intelligence + Capital Governance + Recovery"""
    try:
        from src.phase107_109 import get_phase107_109_status
        status = get_phase107_109_status()
        
        pred = status.get("predictive", {})
        cap = status.get("capital", {})
        rec = status.get("recovery", {})
        
        bias_rows = ""
        for sym, data in sorted(pred.get("last_bias", {}).items())[:10]:
            mult = data.get("mult", 1.0)
            inputs = data.get("inputs", {})
            bias_rows += f"""
                <tr>
                    <td><strong>{sym}</strong></td>
                    <td>{mult:.3f}x</td>
                    <td>{inputs.get('tp', 0):.2f}</td>
                    <td>{inputs.get('vf_bps', 0):.1f}</td>
                    <td>{inputs.get('lq', 0):.2f}</td>
                    <td>{inputs.get('flow', 0.5):.2f}</td>
                </tr>
            """
        
        quality_rows = ""
        for sym, q in sorted(pred.get("prediction_quality", {}).items(), key=lambda x: x[1].get("total", 0), reverse=True)[:10]:
            correct = q.get("correct", 0)
            total = q.get("total", 0)
            pct = (correct / total * 100) if total > 0 else 0
            color = "#00ff88" if pct >= 55 else "#ff4466"
            quality_rows += f"""
                <tr>
                    <td><strong>{sym}</strong></td>
                    <td>{correct}/{total}</td>
                    <td style='color:{color}'>{pct:.1f}%</td>
                </tr>
            """
        
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Phase 10.7-10.9</title>
    <meta http-equiv="refresh" content="30">
    <style>
        body {{ font-family: monospace; background: #0a0a0a; color: #e0e0e0; padding: 20px; }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        .header {{ border-bottom: 2px solid #ff6600; padding-bottom: 10px; margin-bottom: 20px; }}
        .nav {{ margin-bottom: 20px; }}
        .nav a {{ color: #ff6600; text-decoration: none; padding: 10px 20px; background: #1a1a1a; border-radius: 5px; margin-right: 10px; }}
        .card {{ background: #1a1a1a; border: 1px solid #333; padding: 20px; border-radius: 10px; margin-bottom: 20px; }}
        .metric-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin-bottom: 20px; }}
        .metric-box {{ background: #1a1a1a; border: 1px solid #333; padding: 15px; border-radius: 5px; }}
        .metric-label {{ color: #888; font-size: 0.9em; }}
        .metric-value {{ font-size: 1.8em; font-weight: bold; }}
        .table {{ width: 100%; border-collapse: collapse; }}
        .table th {{ background: #222; color: #ff6600; padding: 10px; text-align: left; }}
        .table td {{ padding: 8px; border-bottom: 1px solid #333; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>⚡ Phase 10.7-10.9 — Predictive Intelligence + Capital Governance + Recovery</h1>
            <p style="color: #888;">Real-time predictions, capital ramps, and anomaly detection</p>
        </div>
        <div class="nav">
            <a href="/">← Main</a>
            <a href="/phase102">Phase 10.2</a>
            <a href="/phase10x">Phase 10.3-10.5</a>
            <a href="/phase106">Phase 10.6</a>
            <a href="/phase107_109">Phase 10.7-10.9</a>
        </div>
        
        <div class="card">
            <h2>10.7 Predictive Intelligence</h2>
            <div class="metric-grid">
                <div class="metric-box">
                    <div class="metric-label">Weights Calibrated</div>
                    <div class="metric-value" style="color: #00bfff;">{pred.get('weights_count', 0)}</div>
                </div>
                <div class="metric-box">
                    <div class="metric-label">Symbols Tracked</div>
                    <div class="metric-value" style="color: #ff6600;">{len(pred.get('last_bias', {{}}))}</div>
                </div>
                <div class="metric-box">
                    <div class="metric-label">Quality Tracked</div>
                    <div class="metric-value" style="color: #ffd700;">{len(pred.get('prediction_quality', {{}}))}</div>
                </div>
            </div>
            <h3>Recent Biases</h3>
            <table class="table">
                <tr>
                    <th>Symbol</th>
                    <th>Multiplier</th>
                    <th>Trend Prob</th>
                    <th>Vol (bps)</th>
                    <th>Liquidity</th>
                    <th>Flow</th>
                </tr>
                {bias_rows if bias_rows else "<tr><td colspan='6'>No biases yet</td></tr>"}
            </table>
            <h3>Prediction Quality</h3>
            <table class="table">
                <tr>
                    <th>Symbol</th>
                    <th>Correct/Total</th>
                    <th>Accuracy</th>
                </tr>
                {quality_rows if quality_rows else "<tr><td colspan='3'>No predictions yet</td></tr>"}
            </table>
        </div>
        
        <div class="card">
            <h2>10.8 Capital Governance</h2>
            <div class="metric-grid">
                <div class="metric-box">
                    <div class="metric-label">Futures Cap</div>
                    <div class="metric-value" style="color: #00ff88;">{cap.get('venue_cap_pct', {{}}).get('futures', 0)*100:.0f}%</div>
                    <div class="metric-label">Ramp: {cap.get('current_ramp_idx', {{}}).get('futures', 0)}/3, Ticks: {cap.get('venue_ticks_green', {{}}).get('futures', 0)}</div>
                </div>
                <div class="metric-box">
                    <div class="metric-label">Spot Cap</div>
                    <div class="metric-value" style="color: #ff6600;">{cap.get('venue_cap_pct', {{}}).get('spot', 0)*100:.0f}%</div>
                    <div class="metric-label">Ramp: {cap.get('current_ramp_idx', {{}}).get('spot', 0)}/3, Ticks: {cap.get('venue_ticks_green', {{}}).get('spot', 0)}</div>
                </div>
            </div>
        </div>
        
        <div class="card">
            <h2>10.9 Autonomous Recovery</h2>
            <div class="metric-grid">
                <div class="metric-box">
                    <div class="metric-label">System Status</div>
                    <div class="metric-value" style="color: {'#ff4466' if rec.get('is_frozen') else '#00ff88'};">
                        {'FROZEN' if rec.get('is_frozen') else 'ACTIVE'}
                    </div>
                </div>
                <div class="metric-box">
                    <div class="metric-label">Reactivation Ticks</div>
                    <div class="metric-value" style="color: #ffd700;">{rec.get('reactivation_ticks', 0)}/3</div>
                </div>
                <div class="metric-box">
                    <div class="metric-label">Last Anomaly</div>
                    <div class="metric-value" style="color: #ff6600; font-size: 1.2em;">{rec.get('last_anomaly', 'None')[:20]}</div>
                </div>
            </div>
        </div>
    </div>
</body>
</html>
        """
        return html
    except Exception as e:
        import traceback
        return f"<pre>Error: {str(e)}\n\n{traceback.format_exc()}</pre>", 500

@app.route("/phase106")
def phase106_dashboard():
    """Phase 10.6 Calibration Dashboard"""
    try:
        from src.phase106_calibration import get_phase106_status
        status = get_phase106_status()
        
        exec_q = status.get("exec_quality", {})
        offsets = status.get("limit_offsets_bps", {})
        scenarios = status.get("scenarios", {})
        hygiene = status.get("hygiene", {})
        snapshot = status.get("snapshot", {})
        
        scenario_rows = ""
        for s in scenarios.get("results", []):
            color = "#00ff88" if s.get("passed") else "#ff4466"
            scenario_rows += f"""
                <tr style='background: {"#1a2a1a" if s.get("passed") else "#2a1a1a"}'>
                    <td>{s.get("regime", "")}</td>
                    <td>{s.get("spread_bps", 0):.1f}</td>
                    <td>{s.get("slip_bps", 0):.1f}</td>
                    <td>{s.get("size_mult", 1.0):.2f}x</td>
                    <td style='color:{color}'>{"✓" if s.get("passed") else "✗"}</td>
                    <td style='color:{color}'>{"✓" if s.get("veto") else "-"}</td>
                </tr>
            """
        
        flag_rows = ""
        for f in hygiene.get("flags", []):
            flag_rows += f"""
                <tr>
                    <td>{f.get("cfg_id", "")}</td>
                    <td>{f.get("reason", "")}</td>
                    <td>{f.get("samples", f.get("age_hours", 0))}</td>
                </tr>
            """
        
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Phase 10.6 Calibration</title>
    <meta http-equiv="refresh" content="30">
    <style>
        body {{ font-family: monospace; background: #0a0a0a; color: #e0e0e0; padding: 20px; }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        .header {{ border-bottom: 2px solid #ff6600; padding-bottom: 10px; margin-bottom: 20px; }}
        .nav {{ margin-bottom: 20px; }}
        .nav a {{ color: #ff6600; text-decoration: none; padding: 10px 20px; background: #1a1a1a; border-radius: 5px; margin-right: 10px; }}
        .card {{ background: #1a1a1a; border: 1px solid #333; padding: 20px; border-radius: 10px; margin-bottom: 20px; }}
        .metric-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin-bottom: 20px; }}
        .metric-box {{ background: #1a1a1a; border: 1px solid #333; padding: 15px; border-radius: 5px; }}
        .metric-label {{ color: #888; font-size: 0.9em; }}
        .metric-value {{ font-size: 1.8em; font-weight: bold; }}
        .table {{ width: 100%; border-collapse: collapse; }}
        .table th, .table td {{ padding: 10px; text-align: left; border-bottom: 1px solid #333; }}
        .table th {{ color: #888; font-weight: normal; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>⚡ Phase 10.6 — Calibration & Auto-Tuning</h1>
            <p>Real-time execution tuning, stress tests, and hygiene</p>
        </div>
        <div class="nav">
            <a href="/">← Main</a>
            <a href="/phase102">Phase 10.2</a>
            <a href="/phase10x">Phase 10.3-10.5</a>
            <a href="/phase106">Phase 10.6</a>
        </div>
        <div class="card">
            <h2>Execution Quality</h2>
            <div class="metric-grid">
                <div class="metric-box">
                    <div class="metric-label">Avg Slippage</div>
                    <div class="metric-value" style="color: #ffd700;">{exec_q.get('avg_slip_bps', 0):.1f} bps</div>
                    <div class="metric-label">Target: {exec_q.get('target_slip_bps', 0):.1f} bps</div>
                </div>
                <div class="metric-box">
                    <div class="metric-label">Avg Spread</div>
                    <div class="metric-value" style="color: #00ff88;">{exec_q.get('avg_spread_bps', 0):.1f} bps</div>
                </div>
                <div class="metric-box">
                    <div class="metric-label">Limit Buy Offset</div>
                    <div class="metric-value" style="color: #88ff00;">{offsets.get('buy', 0):.1f} bps</div>
                </div>
                <div class="metric-box">
                    <div class="metric-label">Limit Sell Offset</div>
                    <div class="metric-value" style="color: #ff6600;">{offsets.get('sell', 0):.1f} bps</div>
                </div>
            </div>
        </div>
        <div class="card">
            <h2>Stress Test Scenarios</h2>
            <p style="color: #888;">Passed: {scenarios.get('passed', 0)}/{scenarios.get('total', 0)}</p>
            <table class="table">
                <tr>
                    <th>Regime</th>
                    <th>Spread</th>
                    <th>Slippage</th>
                    <th>Size Mult</th>
                    <th>Passed</th>
                    <th>Veto</th>
                </tr>
                {scenario_rows if scenario_rows else "<tr><td colspan='6'>No scenarios yet</td></tr>"}
            </table>
        </div>
        <div class="card">
            <h2>Hygiene Flags</h2>
            <p style="color: #888;">Total flags: {hygiene.get('total_flags', 0)}</p>
            <table class="table">
                <tr>
                    <th>Config ID</th>
                    <th>Reason</th>
                    <th>Detail</th>
                </tr>
                {flag_rows if flag_rows else "<tr><td colspan='3' style='color:#00ff88'>No hygiene issues</td></tr>"}
            </table>
        </div>
        <div class="card">
            <h2>Snapshot Status</h2>
            <div class="metric-grid" style="grid-template-columns: repeat(2, 1fr);">
                <div class="metric-box">
                    <div class="metric-label">Has Snapshot</div>
                    <div class="metric-value" style="color: {'#00ff88' if snapshot.get('has_snapshot') else '#ff4466'};">{"✓" if snapshot.get('has_snapshot') else "✗"}</div>
                </div>
                <div class="metric-box">
                    <div class="metric-label">Tune Events</div>
                    <div class="metric-value" style="color: #ffd700;">{status.get('tune_history_count', 0)}</div>
                </div>
            </div>
        </div>
    </div>
</body>
</html>
        """
        return html
    except Exception as e:
        import traceback
        return f"<pre>Error: {str(e)}\n\n{traceback.format_exc()}</pre>", 500

@app.route("/phase1013_1015")
def phase1013_1015_dashboard():
    """Phase 10.13-10.15 Dashboard: Expectancy Attribution + Risk Parity + Degradation Auditor"""
    try:
        from src.phase1013_1015 import get_status, get_expectancy_ledger, get_correlation_matrix, get_recent_allocations, get_audit_history
        status = get_status()
        
        p13 = status.get("phase1013", {})
        p14 = status.get("phase1014", {})
        p15 = status.get("phase1015", {})
        
        # Top expectancy signals
        expectancy_rows = ""
        for sig in p13.get("top_expectancy", [])[:10]:
            score = sig.get("expectancy_score", 0)
            color = "#00ff88" if score > 0 else "#ff4466"
            expectancy_rows += f"""
                <tr>
                    <td><strong>{sig.get("symbol", "")}</strong></td>
                    <td>{sig.get("strategy", "")}</td>
                    <td style='color:{color}'>{score:.2f}</td>
                    <td>{sig.get("samples", 0)}</td>
                    <td>{sig.get("avg_edge", 0):.2f}</td>
                    <td>{sig.get("exec_quality", 0):.1f}</td>
                    <td>{sig.get("exit_efficiency", 0):.3f}</td>
                </tr>
            """
        
        # Recent allocations
        allocation_rows = ""
        allocations = get_recent_allocations()
        for sym, alloc in sorted(allocations.items(), key=lambda x: x[1].get("timestamp", 0), reverse=True)[:10]:
            base = alloc.get("base", 0)
            sized = alloc.get("sized", 0)
            reduction = (1 - sized/base) * 100 if base > 0 else 0
            color = "#ff6600" if reduction > 20 else "#ffd700"
            allocation_rows += f"""
                <tr>
                    <td><strong>{sym}</strong></td>
                    <td>{alloc.get("strategy", "")}</td>
                    <td>${base:.2f}</td>
                    <td style='color:{color}'>${sized:.2f}</td>
                    <td>{alloc.get("risk_units", 0):.2f}</td>
                    <td>{alloc.get("cluster_size", 0)}</td>
                    <td>{alloc.get("suppression_factor", 1.0):.2f}x</td>
                </tr>
            """
        
        # Recent degradation repairs
        repair_rows = ""
        for repair in p15.get("recent_repairs", []):
            repair_rows += f"""
                <tr>
                    <td>{repair.get("component", "")}</td>
                    <td>{repair.get("detail", "")}</td>
                </tr>
            """
        
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Phase 10.13-10.15</title>
    <meta http-equiv="refresh" content="30">
    <style>
        body {{ font-family: monospace; background: #0a0a0a; color: #e0e0e0; padding: 20px; }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        .header {{ border-bottom: 2px solid #ff6600; padding-bottom: 10px; margin-bottom: 20px; }}
        .nav {{ margin-bottom: 20px; }}
        .nav a {{ color: #ff6600; text-decoration: none; padding: 10px 20px; background: #1a1a1a; border-radius: 5px; margin-right: 10px; }}
        .card {{ background: #1a1a1a; border: 1px solid #333; padding: 20px; border-radius: 10px; margin-bottom: 20px; }}
        .metric-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin-bottom: 20px; }}
        .metric-box {{ background: #1a1a1a; border: 1px solid #333; padding: 15px; border-radius: 5px; }}
        .metric-label {{ color: #888; font-size: 0.9em; }}
        .metric-value {{ font-size: 1.8em; font-weight: bold; }}
        .table {{ width: 100%; border-collapse: collapse; }}
        .table th {{ background: #222; color: #ff6600; padding: 10px; text-align: left; }}
        .table td {{ padding: 8px; border-bottom: 1px solid #333; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>⚡ Phase 10.13-10.15 — Expectancy + Risk Parity + Degradation Auditor</h1>
            <p style="color: #888;">Attribution tracking, correlation-aware sizing, and system health monitoring</p>
        </div>
        <div class="nav">
            <a href="/">← Main</a>
            <a href="/phase102">Phase 10.2</a>
            <a href="/phase10x">Phase 10.3-10.5</a>
            <a href="/phase106">Phase 10.6</a>
            <a href="/phase107_109">Phase 10.7-10.9</a>
            <a href="/phase1010_1012">Phase 10.10-10.12</a>
            <a href="/phase1013_1015">Phase 10.13-10.15</a>
        </div>
        
        <div class="card">
            <h2>10.13 Expectancy Attribution</h2>
            <div class="metric-grid">
                <div class="metric-box">
                    <div class="metric-label">Ledger Entries</div>
                    <div class="metric-value" style="color: #00bfff;">{p13.get('ledger_entries', 0)}</div>
                </div>
                <div class="metric-box">
                    <div class="metric-label">Last Update</div>
                    <div class="metric-value" style="color: #ffd700; font-size: 1.2em;">{p13.get('last_update', 'Never')}</div>
                </div>
            </div>
            <h3>Top Expectancy Signals</h3>
            <table class="table">
                <tr>
                    <th>Symbol</th>
                    <th>Strategy</th>
                    <th>Expectancy Score</th>
                    <th>Samples</th>
                    <th>Avg Edge</th>
                    <th>Exec Quality (bps)</th>
                    <th>Exit Efficiency</th>
                </tr>
                {expectancy_rows if expectancy_rows else "<tr><td colspan='7'>No expectancy data yet</td></tr>"}
            </table>
        </div>
        
        <div class="card">
            <h2>10.14 Risk Parity Allocation</h2>
            <div class="metric-grid">
                <div class="metric-box">
                    <div class="metric-label">Correlation Pairs</div>
                    <div class="metric-value" style="color: #88ff00;">{p14.get('correlation_pairs', 0)}</div>
                </div>
                <div class="metric-box">
                    <div class="metric-label">Recent Allocations</div>
                    <div class="metric-value" style="color: #00ff88;">{p14.get('recent_allocations', 0)}</div>
                </div>
                <div class="metric-box">
                    <div class="metric-label">Active Clusters</div>
                    <div class="metric-value" style="color: #ff6600;">{p14.get('cluster_count', 0)}</div>
                </div>
            </div>
            <h3>Recent Risk-Parity Allocations</h3>
            <table class="table">
                <tr>
                    <th>Symbol</th>
                    <th>Strategy</th>
                    <th>Base Size</th>
                    <th>Sized (After RP)</th>
                    <th>Risk Units</th>
                    <th>Cluster Size</th>
                    <th>Suppression</th>
                </tr>
                {allocation_rows if allocation_rows else "<tr><td colspan='7'>No allocations yet</td></tr>"}
            </table>
        </div>
        
        <div class="card">
            <h2>10.15 Degradation Auditor</h2>
            <div class="metric-grid">
                <div class="metric-box">
                    <div class="metric-label">Total Issues Detected</div>
                    <div class="metric-value" style="color: #ff6600;">{p15.get('total_issues', 0)}</div>
                </div>
                <div class="metric-box">
                    <div class="metric-label">Total Repairs Applied</div>
                    <div class="metric-value" style="color: #00ff88;">{p15.get('total_repairs', 0)}</div>
                </div>
                <div class="metric-box">
                    <div class="metric-label">Last Audit</div>
                    <div class="metric-value" style="color: #ffd700; font-size: 1.2em;">{p15.get('last_audit', 'Never')}</div>
                </div>
            </div>
            <h3>Recent Degradation Repairs</h3>
            <table class="table">
                <tr>
                    <th>Component</th>
                    <th>Detail</th>
                </tr>
                {repair_rows if repair_rows else "<tr><td colspan='2' style='color:#00ff88'>No repairs needed</td></tr>"}
            </table>
        </div>
    </div>
</body>
</html>
        """
        return html
    except Exception as e:
        import traceback
        return f"<pre>Error: {str(e)}\n\n{traceback.format_exc()}</pre>", 500

@app.route("/phase1016_1018")
def phase1016_1018_dashboard():
    """Phase 10.16-10.18 Dashboard"""
    try:
        from src.phase1016_1018 import get_phase1016_1018_state
        import time
        state = get_phase1016_1018_state()
        p16, p17, p18 = state.get("phase1016", {}), state.get("phase1017", {}), state.get("phase1018", {})
        routing_rows = "".join([f"<tr><td>{b}</td><td style='color:{'#00ff88' if w>1.0 else '#ff6600' if w<1.0 else '#ffd700'}'>{w:.2f}x</td></tr>" for b, w in list(p16.get("routing_weights", {}).items())[:15]])
        hedge_rows = "".join([f"<tr><td>{', '.join(h.get('cluster',[]))}</td><td><strong>{h.get('hedge_symbol','')}</strong></td><td>${h.get('hedge_size_usd',0):.2f}</td><td>${h.get('cluster_exposure',0):.2f}</td></tr>" for h in p17.get("hedges", [])])
        intervention_rows = "".join([f"<tr><td>{i.get('type','')}</td><td>{i.get('reason',i.get('action',''))}</td><td>{i.get('health_score','N/A')}</td></tr>" for i in p18.get("interventions", [])])
        return f"""<!DOCTYPE html><html><head><title>Phase 10.16-10.18</title><meta http-equiv="refresh" content="30"><style>body{{font-family:monospace;background:#0a0a0a;color:#e0e0e0;padding:20px}}.container{{max-width:1400px;margin:0 auto}}.header{{border-bottom:2px solid #ff6600;padding-bottom:10px;margin-bottom:20px}}.nav{{margin-bottom:20px}}.nav a{{color:#ff6600;text-decoration:none;padding:10px 20px;background:#1a1a1a;border-radius:5px;margin-right:10px}}.card{{background:#1a1a1a;padding:20px;margin:20px 0;border-radius:10px;border:1px solid #333}}.metric-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:15px}}.metric-box{{background:#0f0f0f;padding:15px;border-radius:8px;text-align:center}}.metric-label{{color:#888;font-size:0.9em;margin-bottom:5px}}.metric-value{{font-size:1.8em;font-weight:bold}}.table{{width:100%;border-collapse:collapse;margin-top:15px}}.table th{{background:#0f0f0f;padding:12px;text-align:left;border-bottom:2px solid #ff6600}}.table td{{padding:10px;border-bottom:1px solid #333}}</style></head><body><div class="container"><div class="header"><h1>Phase 10.16-10.18</h1><p>Meta Router · Hedger · Governance</p></div><div class="nav"><a href="/">Home</a><a href="/phase8">Phase 8</a><a href="/phase93">Venue</a><a href="/phase1013_1015">10.13-15</a><a href="/unified">Unified</a></div><div class="card"><h2>10.16 Meta-Expectancy Router</h2><div class="metric-grid"><div class="metric-box"><div class="metric-label">Buckets</div><div class="metric-value" style="color:#ffd700">{p16.get('bucket_count',0)}</div></div><div class="metric-box"><div class="metric-label">High Tier</div><div class="metric-value" style="color:#00ff88">{p16.get('tiers',{}).get('high',0)}</div></div><div class="metric-box"><div class="metric-label">Low Tier</div><div class="metric-value" style="color:#ff4466">{p16.get('tiers',{}).get('low',0)}</div></div></div><h3>Routing Weights</h3><table class="table"><tr><th>Bucket</th><th>Multiplier</th></tr>{routing_rows or "<tr><td colspan='2'>No data</td></tr>"}</table></div><div class="card"><h2>10.17 Correlation Hedger</h2><div class="metric-grid"><div class="metric-box"><div class="metric-label">Correlation Pairs</div><div class="metric-value" style="color:#ffd700">{p17.get('correlation_pairs',0)}</div></div><div class="metric-box"><div class="metric-label">Active Hedges</div><div class="metric-value" style="color:#ff6600">{p17.get('active_hedges',0)}</div></div><div class="metric-box"><div class="metric-label">Last Update</div><div class="metric-value" style="color:#00ff88;font-size:1.2em">{p17.get('last_hedge_ts',0)}</div></div></div><h3>Active Hedges</h3><table class="table"><tr><th>Cluster</th><th>Hedge</th><th>Size</th><th>Exposure</th></tr>{hedge_rows or "<tr><td colspan='4' style='color:#00ff88'>No hedges</td></tr>"}</table></div><div class="card"><h2>10.18 Autonomous Governance</h2><div class="metric-grid"><div class="metric-box"><div class="metric-label">Health</div><div class="metric-value" style="color:{'#00ff88' if p18.get('health_score',0)>0.7 else '#ff6600' if p18.get('health_score',0)>0.4 else '#ff4466'}">{p18.get('health_score',0):.2f}</div></div><div class="metric-box"><div class="metric-label">Circuit Breaker</div><div class="metric-value" style="color:{'#ff4466' if p18.get('circuit_breaker_active') else '#00ff88'}">{"ACTIVE" if p18.get('circuit_breaker_active') else "OFF"}</div></div><div class="metric-box"><div class="metric-label">Errors</div><div class="metric-value" style="color:#ff6600">{p18.get('consecutive_errors',0)}</div></div></div><h3>Interventions</h3><table class="table"><tr><th>Type</th><th>Reason</th><th>Health</th></tr>{intervention_rows or "<tr><td colspan='3' style='color:#00ff88'>No interventions</td></tr>"}</table></div></div></body></html>"""
    except Exception as e:
        import traceback
        return f"<pre>Error: {str(e)}\n\n{traceback.format_exc()}</pre>", 500

@app.route("/unified")
def unified_dashboard():
    """Unified Stack Dashboard"""
    try:
        from src.unified_stack import get_unified_state
        import time
        state = get_unified_state()
        tick_rows = "".join([f"<tr><td>{n}</td><td style='color:{'#00ff88' if (int(time.time())-t)<600 else '#ffd700' if (int(time.time())-t)<1200 else '#ff6600'}'>{int(time.time())-t}s ago</td></tr>" for n, t in sorted(state.get("ticks",{}).items(),key=lambda x:x[1],reverse=True)[:20]])
        error_rows = "".join([f"<tr><td>{e.get('stage','')}</td><td style='color:#ff4466'>{e.get('err','')[:100]}</td></tr>" for e in state.get("errors",[])[-10:]])
        uptime_h = state.get("uptime_sec",0)/3600
        return f"""<!DOCTYPE html><html><head><title>Unified Stack</title><meta http-equiv="refresh" content="30"><style>body{{font-family:monospace;background:#0a0a0a;color:#e0e0e0;padding:20px}}.container{{max-width:1400px;margin:0 auto}}.header{{border-bottom:2px solid #00ff88;padding-bottom:10px;margin-bottom:20px}}.nav{{margin-bottom:20px}}.nav a{{color:#00ff88;text-decoration:none;padding:10px 20px;background:#1a1a1a;border-radius:5px;margin-right:10px}}.card{{background:#1a1a1a;padding:20px;margin:20px 0;border-radius:10px;border:1px solid #333}}.metric-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:15px}}.metric-box{{background:#0f0f0f;padding:15px;border-radius:8px;text-align:center}}.metric-label{{color:#888;font-size:0.9em;margin-bottom:5px}}.metric-value{{font-size:1.8em;font-weight:bold}}.table{{width:100%;border-collapse:collapse;margin-top:15px}}.table th{{background:#0f0f0f;padding:12px;text-align:left;border-bottom:2px solid #00ff88}}.table td{{padding:10px;border-bottom:1px solid #333}}</style></head><body><div class="container"><div class="header"><h1>🌐 Unified Stack</h1><p>Phases 9.3-10.18 Orchestration</p></div><div class="nav"><a href="/">Home</a><a href="/phase8">Phase 8</a><a href="/phase93">Venue</a><a href="/phase102">Futures</a><a href="/phase1013_1015">10.13-15</a><a href="/phase1016_1018">10.16-18</a></div><div class="card"><h2>System Status</h2><div class="metric-grid"><div class="metric-box"><div class="metric-label">Uptime</div><div class="metric-value" style="color:#00ff88">{uptime_h:.1f}h</div></div><div class="metric-box"><div class="metric-label">Active Ticks</div><div class="metric-value" style="color:#ffd700">{len(state.get('ticks',{}))}</div></div><div class="metric-box"><div class="metric-label">Errors</div><div class="metric-value" style="color:{'#ff4466' if len(state.get('errors',[]))>5 else '#ffd700'}">{len(state.get('errors',[]))}</div></div></div></div><div class="card"><h2>Recent Ticks (Last 20)</h2><table class="table"><tr><th>Tick</th><th>Last Run</th></tr>{tick_rows or "<tr><td colspan='2'>No ticks</td></tr>"}</table></div><div class="card"><h2>Recent Errors (Last 10)</h2><table class="table"><tr><th>Stage</th><th>Error</th></tr>{error_rows or "<tr><td colspan='2' style='color:#00ff88'>No errors</td></tr>"}</table></div><div class="card"><h2>Integrated Phases</h2><ul style="columns:2;column-gap:40px"><li>9.3 Venue Governance</li><li>9.4 Recovery & Ramps</li><li>10.0 Profit Gates</li><li>10.1 Attribution Allocator</li><li>10.2 Futures Optimizer</li><li>10.3 Adaptive Risk</li><li>10.4 Execution Efficiency</li><li>10.5 Experiments</li><li>10.6 Calibration</li><li>10.7 Predictive Intelligence</li><li>10.8 Capital Governance</li><li>10.9 Autonomous Recovery</li><li>10.10 Collaborative Intelligence</li><li>10.11 Cross-Venue Arbitrage</li><li>10.12 Operator Controls</li><li>10.13 Expectancy Attribution</li><li>10.14 Risk Parity</li><li>10.15 Degradation Auditor</li><li>10.16 Meta-Expectancy Router</li><li>10.17 Correlation Hedger</li><li>10.18 Autonomous Governance</li></ul></div></div></body></html>"""
    except Exception as e:
        import traceback
        return f"<pre>Error: {str(e)}\n\n{traceback.format_exc()}</pre>", 500

@app.route("/phase11")
def phase11_performance():
    """Phase 11.0 Unified Self-Governance Performance Dashboard."""
    from trading_performance_dashboard import generate_performance_comparison
    
    # Regenerate chart with latest data
    chart_path = generate_performance_comparison()
    
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Phase 11.0 Performance Dashboard</title>
        <meta http-equiv="refresh" content="30">
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; background: #0a0a0a; color: #e0e0e0; }
            .container { max-width: 1200px; margin: 0 auto; background: #1a1a1a; padding: 30px; border-radius: 10px; border: 1px solid #333; }
            h1 { color: #00ff88; border-bottom: 3px solid #00ff88; padding-bottom: 10px; }
            h2 { color: #ffd700; margin-top: 30px; }
            .metric { background: #0f0f0f; padding: 15px; margin: 10px 0; border-left: 4px solid #00ff88; }
            .improvement { color: #00ff88; font-weight: bold; }
            .warning { color: #ff6600; font-weight: bold; }
            img { max-width: 100%; height: auto; margin: 20px 0; border: 1px solid #333; border-radius: 5px; }
            .features { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin: 20px 0; }
            .feature { background: #0f0f0f; border: 1px solid #333; padding: 15px; border-radius: 5px; }
            .feature h3 { color: #ff6600; margin-top: 0; }
            .back-link { display: inline-block; margin-top: 20px; padding: 10px 20px; background: #00ff88; color: #0a0a0a; text-decoration: none; border-radius: 5px; font-weight: bold; }
            .back-link:hover { background: #00cc66; }
            code { background: #0f0f0f; padding: 2px 6px; border-radius: 3px; color: #ff6600; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🛡️ Phase 11.0: Unified Self-Governance</h1>
            <p><strong>Revolutionary Profitability Fix</strong> - Complete replacement of scattered governance patches with cohesive self-governing system</p>
            
            <h2>📊 Performance Comparison</h2>
            <img src="/static/phase11/performance_comparison.png" alt="Performance Comparison Chart">
            
            <h2>🎯 Key Metrics</h2>
            <div class="metric">
                <strong>Win Rate</strong><br>
                Pre-Phase 11.0: <span class="warning">0.5%</span> (1 win / 199 trades)<br>
                Post-Phase 11.0: <span class="improvement">40.0% (expected)</span><br>
                <span class="improvement">+79x improvement</span>
            </div>
            
            <div class="metric">
                <strong>Realized P&L</strong><br>
                Pre-Phase 11.0: <span class="warning">-$60.74</span><br>
                Post-Phase 11.0: <span class="improvement">+$50.00 (expected)</span><br>
                <span class="improvement">+$110.74 turnaround</span>
            </div>
            
            <div class="metric">
                <strong>Fees Paid</strong><br>
                Pre-Phase 11.0: <span class="warning">$123.25</span> (fee bleeding)<br>
                Post-Phase 11.0: <span class="improvement">$30.00 (expected)</span><br>
                <span class="improvement">-76% reduction</span>
            </div>
            
            <div class="metric">
                <strong>Net Portfolio Change</strong><br>
                Pre-Phase 11.0: <span class="warning">+$23.78</span> (unrealized only)<br>
                Post-Phase 11.0: <span class="improvement">+$80.00 (expected)</span><br>
                <span class="improvement">+$56.22 increase (+237%)</span>
            </div>
            
            <h2>🔧 Critical Fixes Implemented</h2>
            <div class="features">
                <div class="feature">
                    <h3>💰 Fee-Aware Profit Filtering</h3>
                    <p>Entry requires expected profit ≥ 2× round-trip fees (0.24% min)</p>
                    <p><strong>Impact:</strong> Blocks unprofitable micro-trades</p>
                </div>
                
                <div class="feature">
                    <h3>🔄 Churn Protection</h3>
                    <p>Max 4 entries/hour, 10-min cooldown, 5-min minimum hold</p>
                    <p><strong>Impact:</strong> Stops TRXUSDT fee bleeding (22 consecutive losses)</p>
                </div>
                
                <div class="feature">
                    <h3>📊 Real Outcome Feedback</h3>
                    <p>Tracks win rate & P&L over 50-trade windows per symbol</p>
                    <p><strong>Impact:</strong> Auto-disables <40% win rate or negative P&L</p>
                </div>
                
                <div class="feature">
                    <h3>🎯 TRXUSDT Overrides</h3>
                    <p>Min $5 profit threshold, max 1x leverage until WR>50%</p>
                    <p><strong>Impact:</strong> Special protection for worst performer</p>
                </div>
                
                <div class="feature">
                    <h3>⚙️ Autonomous Cycles</h3>
                    <p>Tactical (15min), Strategic (daily), Reconciliation (hourly)</p>
                    <p><strong>Impact:</strong> Self-adjusting policy optimization</p>
                </div>
                
                <div class="feature">
                    <h3>🚨 Watchdog with Freeze</h3>
                    <p>Monitors 5 health metrics, freezes entries 15min if issues</p>
                    <p><strong>Impact:</strong> Protects against degraded conditions</p>
                </div>
            </div>
            
            <h2>📈 Expected Timeline</h2>
            <ul>
                <li><strong>0-24 hours:</strong> Initial fee-aware blocks, churn protection activates</li>
                <li><strong>24-48 hours:</strong> First symbol performance reviews</li>
                <li><strong>48-72 hours:</strong> Policy adjustments based on real outcomes</li>
                <li><strong>Week 1:</strong> Full profitability turnaround visible</li>
            </ul>
            
            <h2>🔍 Monitoring</h2>
            <p>Track real performance in <code>logs/unified_events.jsonl</code>:</p>
            <ul>
                <li><code>fee_aware_block</code> - Trades rejected for insufficient profit</li>
                <li><code>entry_block_churn_guard</code> - Churn protection activations</li>
                <li><code>symbol_auto_disabled</code> - Poor performers auto-disabled</li>
                <li><code>entries_frozen</code> - Watchdog-triggered freeze events</li>
                <li><code>profit_policy_adjusted</code> - Autonomous policy changes</li>
            </ul>
            
            <a href="/" class="back-link">← Back to Main Dashboard</a>
        </div>
    </body>
    </html>
    """

@app.route("/static/phase11/<path:filename>")
def serve_phase11_static(filename):
    """Serve Phase 11 static files."""
    import os
    from flask import send_from_directory
    static_dir = os.path.join(os.path.dirname(__file__), 'static')
    return send_from_directory(static_dir, filename)


@app.route("/api/learning/state")
def api_learning_state():
    """Get current learning state."""
    try:
        from src.continuous_learning_controller import get_learning_state
        state = get_learning_state()
        return jsonify(state)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/learning/run", methods=["POST"])
def api_learning_run():
    """Trigger a learning cycle."""
    try:
        from src.continuous_learning_controller import run_learning_cycle, apply_adjustments
        state = run_learning_cycle(force=True)
        dry_run = request.args.get("dry_run", "true").lower() == "true"
        result = apply_adjustments(dry_run=dry_run)
        return jsonify({"state": state, "applied": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/learning")
def learning_dashboard():
    """Continuous Learning Dashboard - Shows what the system is learning and adjusting."""
    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Continuous Learning Dashboard</title>
<meta http-equiv="refresh" content="60">
<style>
    body { font-family: system-ui, Arial; margin: 20px; background: #0a0a0a; color: #e0e0e0; }
    .container { max-width: 1400px; margin: 0 auto; }
    .header { display: flex; align-items: center; gap: 20px; margin-bottom: 20px; }
    h1 { color: #00ff88; margin: 0; }
    .card { background: #1a1a1a; padding: 20px; border-radius: 10px; margin-bottom: 20px; border: 1px solid #333; }
    .card h2 { color: #ffd700; margin-top: 0; border-bottom: 2px solid #ffd700; padding-bottom: 10px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; }
    .metric { background: #0f0f0f; padding: 15px; border-radius: 5px; }
    .metric-value { font-size: 2em; font-weight: bold; color: #00ff88; }
    .metric-label { color: #888; font-size: 0.9em; }
    table { width: 100%; border-collapse: collapse; }
    th, td { padding: 10px; text-align: left; border-bottom: 1px solid #333; }
    th { color: #ffd700; background: #151515; }
    .positive { color: #00ff88; }
    .negative { color: #ff4444; }
    .neutral { color: #888; }
    .back-link { padding: 10px 20px; background: #00ff88; color: #0a0a0a; text-decoration: none; border-radius: 5px; font-weight: bold; }
    .back-link:hover { background: #00cc66; }
    .adjustment { background: #1a2a1a; border-left: 4px solid #00ff88; padding: 10px; margin: 5px 0; border-radius: 0 5px 5px 0; }
    .adjustment.warning { background: #2a2a1a; border-color: #ffd700; }
    .adjustment.danger { background: #2a1a1a; border-color: #ff4444; }
    .pill { display: inline-block; padding: 3px 8px; border-radius: 10px; font-size: 0.8em; }
    .pill-green { background: #1a2a1a; color: #00ff88; }
    .pill-yellow { background: #2a2a1a; color: #ffd700; }
    .pill-red { background: #2a1a1a; color: #ff4444; }
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>🧠 Continuous Learning Dashboard</h1>
        <a href="/" class="back-link">← Back</a>
        <a href="/phase8" class="back-link" style="background: #333; color: #fff;">Trader Dashboard</a>
    </div>
    
    <div class="card">
        <h2>📊 Learning Loop Status</h2>
        <div class="grid">
            <div class="metric">
                <div class="metric-value" id="executed-count">—</div>
                <div class="metric-label">Executed Trades Analyzed</div>
            </div>
            <div class="metric">
                <div class="metric-value" id="blocked-count">—</div>
                <div class="metric-label">Blocked Signals Tracked</div>
            </div>
            <div class="metric">
                <div class="metric-value" id="counterfactual-count">—</div>
                <div class="metric-label">Counterfactuals Computed</div>
            </div>
            <div class="metric">
                <div class="metric-value" id="missed-count">—</div>
                <div class="metric-label">Missed Opportunities Found</div>
            </div>
        </div>
    </div>
    
    <div class="grid">
        <div class="card">
            <h2>📈 Profitability by Dimension</h2>
            <div id="profitability-summary">
                <p class="neutral">Loading...</p>
            </div>
        </div>
        
        <div class="card">
            <h2>🎯 Signal Component Lift</h2>
            <div id="signal-weights">
                <p class="neutral">Loading...</p>
            </div>
        </div>
    </div>
    
    <div class="card">
        <h2>🔧 Recent Adjustments</h2>
        <div id="adjustments">
            <p class="neutral">Loading...</p>
        </div>
    </div>
    
    <div class="card">
        <h2>💀 Killed Combos (Auto-Blocked)</h2>
        <div id="killed-combos">
            <p class="neutral">Loading...</p>
        </div>
    </div>
    
    <div class="card">
        <h2>⏰ Learning Cadence</h2>
        <div class="grid">
            <div class="metric">
                <div class="metric-value" id="last-fast">—</div>
                <div class="metric-label">Last Fast Cycle (30min)</div>
            </div>
            <div class="metric">
                <div class="metric-value" id="last-daily">—</div>
                <div class="metric-label">Last Daily Cycle</div>
            </div>
            <div class="metric">
                <div class="metric-value" id="last-weekly">—</div>
                <div class="metric-label">Last Weekly Cycle</div>
            </div>
        </div>
    </div>
</div>

<script>
async function loadLearningState() {
    try {
        const res = await fetch('/api/learning/state');
        const state = await res.json();
        
        // Samples
        const samples = state.samples || {};
        document.getElementById('executed-count').textContent = samples.executed || 0;
        document.getElementById('blocked-count').textContent = samples.blocked || 0;
        document.getElementById('counterfactual-count').textContent = samples.counterfactual_tracked || 0;
        document.getElementById('missed-count').textContent = samples.missed_found || 0;
        
        // Profitability
        const prof = state.profitability || {};
        let profHtml = '';
        if (prof.by_conviction) {
            profHtml += '<h4>By Conviction Level</h4><table><tr><th>Level</th><th>Count</th><th>Win Rate</th><th>P&L</th></tr>';
            for (const [level, data] of Object.entries(prof.by_conviction)) {
                const wr = data.win_rate ? (data.win_rate * 100).toFixed(1) + '%' : '—';
                const pnl = data.total_pnl ? '$' + data.total_pnl.toFixed(2) : '—';
                const pnlClass = (data.total_pnl || 0) >= 0 ? 'positive' : 'negative';
                profHtml += `<tr><td>${level}</td><td>${data.count || 0}</td><td>${wr}</td><td class="${pnlClass}">${pnl}</td></tr>`;
            }
            profHtml += '</table>';
        }
        document.getElementById('profitability-summary').innerHTML = profHtml || '<p class="neutral">No data yet</p>';
        
        // Signal weights
        const weights = state.weights || {};
        let weightsHtml = '';
        if (weights.component_weights) {
            weightsHtml += '<table><tr><th>Component</th><th>Weight</th><th>Lift</th></tr>';
            for (const [comp, weight] of Object.entries(weights.component_weights)) {
                const lift = weight > 0.15 ? '📈' : (weight < 0.10 ? '📉' : '➡️');
                weightsHtml += `<tr><td>${comp}</td><td>${(weight * 100).toFixed(1)}%</td><td>${lift}</td></tr>`;
            }
            weightsHtml += '</table>';
        }
        document.getElementById('signal-weights').innerHTML = weightsHtml || '<p class="neutral">Default weights</p>';
        
        // Adjustments
        const adjustments = state.adjustments || [];
        let adjHtml = '';
        if (adjustments.length > 0) {
            for (const adj of adjustments.slice(0, 10)) {
                const cls = adj.confidence > 0.7 ? '' : (adj.confidence > 0.4 ? 'warning' : 'danger');
                adjHtml += `<div class="adjustment ${cls}">
                    <strong>${adj.target || 'Unknown'}</strong>: ${adj.reason || 'No reason'}
                    <span class="pill ${adj.applied ? 'pill-green' : 'pill-yellow'}">${adj.applied ? 'Applied' : 'Pending'}</span>
                </div>`;
            }
        } else {
            adjHtml = '<p class="neutral">No adjustments generated yet</p>';
        }
        document.getElementById('adjustments').innerHTML = adjHtml;
        
        // Killed combos
        const gate = state.gate_feedback || {};
        const killed = gate.killed_candidates || [];
        let killedHtml = '';
        if (killed.length > 0) {
            killedHtml = '<table><tr><th>Combo</th><th>Win Rate</th><th>Trades</th><th>Reason</th></tr>';
            for (const k of killed) {
                killedHtml += `<tr><td class="negative">${k.combo || '—'}</td><td>${((k.win_rate || 0) * 100).toFixed(1)}%</td><td>${k.trades || 0}</td><td>${k.reason || '—'}</td></tr>`;
            }
            killedHtml += '</table>';
        } else {
            killedHtml = '<p class="neutral">No combos killed yet</p>';
        }
        document.getElementById('killed-combos').innerHTML = killedHtml;
        
        // Cadence
        const cadence = state.cadence || {};
        const now = Date.now() / 1000;
        const formatAge = (ts) => {
            if (!ts) return 'Never';
            const age = now - ts;
            if (age < 60) return Math.round(age) + 's ago';
            if (age < 3600) return Math.round(age / 60) + 'm ago';
            if (age < 86400) return Math.round(age / 3600) + 'h ago';
            return Math.round(age / 86400) + 'd ago';
        };
        document.getElementById('last-fast').textContent = formatAge(cadence.last_fast);
        document.getElementById('last-daily').textContent = formatAge(cadence.last_daily);
        document.getElementById('last-weekly').textContent = formatAge(cadence.last_weekly);
        
    } catch (e) {
        console.error('Error loading learning state:', e);
    }
}

loadLearningState();
setInterval(loadLearningState, 60000);
</script>
</body>
</html>"""
    return html
