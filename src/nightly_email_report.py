# src/nightly_email_report.py
#
# Nightly Email Report – Full 24h snapshot with HTML graphs, tables, and actionable insights.
# Runs immediately after the full nightly update. Sends a single rich HTML email.
#
# Contents:
#   - Portfolio overview (WR, PF, EV) and daily P&L
#   - Per-asset summary (top movers, capacity health)
#   - Canary outcomes (pass/fail reasons, retries)
#   - Tag coverage health (blocklisted assets if any)
#   - Venue profile changes (mode/slices/delays)
#   - Signal attribution highlights (best per asset)
#   - Audit links and counts
#   - Inline HTML graphs (SVG) for P&L and portfolio metrics
#
# SMTP:
#   - Uses your email and an SMTP password from environment (e.g., REPLIT SMTP secret)
#   - Set env variables:
#       REPORT_TO_EMAIL=mlevitan96@gmail.com
#       SMTP_USER=your_smtp_username_or_email
#       SMTP_PASS=your_smtp_password (e.g., from Replit secrets)
#       SMTP_HOST=smtp.gmail.com (or your SMTP host)
#       SMTP_PORT=587
#
# Integration:
#   - Call send_nightly_email_report(...) at the end of your nightly pipeline.
#   - It reads from configs/logs produced by your modules; falls back gracefully if missing.

import os, json, time, smtplib, math
from statistics import mean
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# Paths
CONFIG_DIR = "configs"
LOG_DIR = "logs"

REGISTRY_PATH = os.path.join(CONFIG_DIR, "strategy_registry.json")
INTRA_APPLIED_PATH = os.path.join(CONFIG_DIR, "intraday_applied.json")
VENUE_24H_PATH = os.path.join(CONFIG_DIR, "venue_profiles_24h.json")
TAG_AUDIT_LOG = os.path.join(LOG_DIR, "operators_consolidation.jsonl")
ATTR_LOG = os.path.join(LOG_DIR, "signal_attribution.jsonl")
SCHED_LOG = os.path.join(LOG_DIR, "intraday_scheduler.jsonl")
UPLIFT_LOG = os.path.join(LOG_DIR, "intraday_uplift.jsonl")
ULTRA_LOG = os.path.join(LOG_DIR, "ultra_uplift_unified.jsonl")
PROMOTER_LOG = os.path.join(LOG_DIR, "relative_uplift_promoter.jsonl")
PROFIT_PUSH_LOG = os.path.join(LOG_DIR, "profit_push_engine.jsonl")
INTRADAY_ENGINE_LOG = os.path.join(LOG_DIR, "intraday_engine.jsonl")

ASSETS = [
    "BTCUSDT","ETHUSDT","SOLUSDT","AVAXUSDT","DOTUSDT","TRXUSDT",
    "XRPUSDT","ADAUSDT","DOGEUSDT","BNBUSDT","MATICUSDT","LINKUSDT",
    "ARBUSDT","OPUSDT","PEPEUSDT"
]

COMPREHENSIVE_ANALYSIS_PATH = "feature_store/comprehensive_analysis.json"
DAILY_LEARNING_RULES_PATH = "feature_store/daily_learning_rules.json"
FEEDBACK_SUMMARY_PATH = "feature_store/feedback_loop_summary.json"

# Dual-bot comparison paths
ALPHA_PORTFOLIO = "logs/alpha/portfolio.json"
BETA_PORTFOLIO = "logs/beta/portfolio.json"
ALPHA_LEARNING = "feature_store/alpha/daily_learning_rules.json"
BETA_LEARNING = "feature_store/beta/daily_learning_rules.json"

def _now(): return int(time.time())
def _ts(): return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())

def _read_json(path, default=None):
    if not os.path.exists(path): return default
    try:
        with open(path,"r") as f: return json.load(f)
    except:
        return default

def _read_jsonl(path, limit=500):
    items = []
    if not os.path.exists(path): return items
    try:
        with open(path,"r") as f:
            for line in f:
                line=line.strip()
                if not line: continue
                try:
                    items.append(json.loads(line))
                except:
                    continue
    except:
        pass
    return items[-limit:]


def load_dual_bot_comparison():
    """Load Alpha vs Beta bot performance comparison data."""
    alpha_portfolio = _read_json(ALPHA_PORTFOLIO, default={})
    beta_portfolio = _read_json(BETA_PORTFOLIO, default={})
    alpha_learning = _read_json(ALPHA_LEARNING, default={})
    beta_learning = _read_json(BETA_LEARNING, default={})
    
    def compute_stats(portfolio):
        trades = portfolio.get('trades', [])
        if not trades:
            return {
                "total_trades": 0,
                "win_rate": 0,
                "realized_pnl": portfolio.get('realized_pnl', 0),
                "current_value": portfolio.get('current_value', 10000),
                "starting_capital": portfolio.get('starting_capital', 10000),
                "avg_pnl": 0,
                "best_trade": 0,
                "worst_trade": 0,
                "wins": 0,
                "losses": 0
            }
        
        wins = [t for t in trades if t.get('pnl', 0) > 0]
        losses = [t for t in trades if t.get('pnl', 0) < 0]
        pnls = [t.get('pnl', 0) for t in trades]
        
        return {
            "total_trades": len(trades),
            "win_rate": len(wins) / len(trades) * 100 if trades else 0,
            "realized_pnl": portfolio.get('realized_pnl', sum(pnls)),
            "current_value": portfolio.get('current_value', 10000),
            "starting_capital": portfolio.get('starting_capital', 10000),
            "avg_pnl": sum(pnls) / len(trades) if trades else 0,
            "best_trade": max(pnls) if pnls else 0,
            "worst_trade": min(pnls) if pnls else 0,
            "wins": len(wins),
            "losses": len(losses)
        }
    
    alpha_stats = compute_stats(alpha_portfolio)
    beta_stats = compute_stats(beta_portfolio)
    
    # Compute deltas
    pnl_delta = beta_stats['realized_pnl'] - alpha_stats['realized_pnl']
    wr_delta = beta_stats['win_rate'] - alpha_stats['win_rate']
    trade_delta = beta_stats['total_trades'] - alpha_stats['total_trades']
    
    # Determine leader
    if pnl_delta > 0:
        leader = "BETA"
        leader_reason = f"Beta ahead by ${pnl_delta:.2f}"
    elif pnl_delta < 0:
        leader = "ALPHA"
        leader_reason = f"Alpha ahead by ${-pnl_delta:.2f}"
    else:
        leader = "TIE"
        leader_reason = "Both strategies performing equally"
    
    # Get tier breakdown for Beta
    beta_trades = beta_portfolio.get('trades', [])
    tier_breakdown = {"A": 0, "B": 0, "C": 0, "D": 0, "F": 0}
    inverted_count = 0
    for t in beta_trades:
        tier = t.get('tier', 'C')
        if tier in tier_breakdown:
            tier_breakdown[tier] += 1
        if t.get('inverted', False):
            inverted_count += 1
    
    return {
        "alpha": alpha_stats,
        "beta": beta_stats,
        "pnl_delta": pnl_delta,
        "wr_delta": wr_delta,
        "trade_delta": trade_delta,
        "leader": leader,
        "leader_reason": leader_reason,
        "beta_tier_breakdown": tier_breakdown,
        "beta_inverted_count": inverted_count,
        "alpha_learning": alpha_learning,
        "beta_learning": beta_learning
    }


def build_dual_bot_comparison_html():
    """Build HTML section for Alpha vs Beta bot comparison."""
    data = load_dual_bot_comparison()
    alpha = data['alpha']
    beta = data['beta']
    
    leader_color = '#2b8a3e' if data['leader'] == 'BETA' else '#1971c2'
    pnl_delta_color = '#2b8a3e' if data['pnl_delta'] >= 0 else '#c92a2a'
    wr_delta_color = '#2b8a3e' if data['wr_delta'] >= 0 else '#c92a2a'
    
    html = """
    <div class='section' style='background: linear-gradient(135deg, #1e3a5f 0%, #2d4a6f 100%); border-radius: 12px; padding: 20px; margin: 20px 0;'>
        <h2 style='color: #ffffff; border-bottom: 2px solid #4dabf7; padding-bottom: 10px;'>
            Alpha vs Beta Strategy Comparison
        </h2>
        
        <div style='display: flex; gap: 20px; flex-wrap: wrap;'>
    """
    
    # Alpha bot card
    alpha_pnl_color = '#2b8a3e' if alpha['realized_pnl'] >= 0 else '#c92a2a'
    html += f"""
            <div style='flex: 1; min-width: 250px; background: #0d1b2a; border-radius: 8px; padding: 15px; border-left: 4px solid #1971c2;'>
                <h3 style='color: #1971c2; margin-top: 0;'>ALPHA BOT</h3>
                <p style='color: #adb5bd; font-size: 12px;'>Baseline Strategy (Weighted Signal Fusion)</p>
                <table style='width: 100%; border: none;'>
                    <tr><td style='border: none; color: #868e96;'>Total Trades</td><td style='border: none; color: #fff; text-align: right;'>{alpha['total_trades']}</td></tr>
                    <tr><td style='border: none; color: #868e96;'>Win Rate</td><td style='border: none; color: #fff; text-align: right;'>{alpha['win_rate']:.1f}%</td></tr>
                    <tr><td style='border: none; color: #868e96;'>Realized P&L</td><td style='border: none; color: {alpha_pnl_color}; text-align: right; font-weight: bold;'>${alpha['realized_pnl']:.2f}</td></tr>
                    <tr><td style='border: none; color: #868e96;'>Portfolio Value</td><td style='border: none; color: #fff; text-align: right;'>${alpha['current_value']:.2f}</td></tr>
                    <tr><td style='border: none; color: #868e96;'>Avg Trade P&L</td><td style='border: none; color: #fff; text-align: right;'>${alpha['avg_pnl']:.2f}</td></tr>
                </table>
            </div>
    """
    
    # Beta bot card
    beta_pnl_color = '#2b8a3e' if beta['realized_pnl'] >= 0 else '#c92a2a'
    html += f"""
            <div style='flex: 1; min-width: 250px; background: #0d1b2a; border-radius: 8px; padding: 15px; border-left: 4px solid #9c36b5;'>
                <h3 style='color: #9c36b5; margin-top: 0;'>BETA BOT</h3>
                <p style='color: #adb5bd; font-size: 12px;'>F-Tier Signal Inversion Strategy</p>
                <table style='width: 100%; border: none;'>
                    <tr><td style='border: none; color: #868e96;'>Total Trades</td><td style='border: none; color: #fff; text-align: right;'>{beta['total_trades']}</td></tr>
                    <tr><td style='border: none; color: #868e96;'>Win Rate</td><td style='border: none; color: #fff; text-align: right;'>{beta['win_rate']:.1f}%</td></tr>
                    <tr><td style='border: none; color: #868e96;'>Realized P&L</td><td style='border: none; color: {beta_pnl_color}; text-align: right; font-weight: bold;'>${beta['realized_pnl']:.2f}</td></tr>
                    <tr><td style='border: none; color: #868e96;'>Portfolio Value</td><td style='border: none; color: #fff; text-align: right;'>${beta['current_value']:.2f}</td></tr>
                    <tr><td style='border: none; color: #868e96;'>Inverted Trades</td><td style='border: none; color: #da77f2; text-align: right;'>{data['beta_inverted_count']}</td></tr>
                </table>
            </div>
    """
    
    html += "</div>"
    
    # Leader banner
    html += f"""
        <div style='background: {leader_color}; border-radius: 8px; padding: 15px; margin-top: 20px; text-align: center;'>
            <h3 style='color: #fff; margin: 0;'>CURRENT LEADER: {data['leader']}</h3>
            <p style='color: #fff; margin: 5px 0 0 0; opacity: 0.9;'>{data['leader_reason']}</p>
        </div>
    """
    
    # Delta metrics
    html += f"""
        <div style='display: flex; gap: 15px; margin-top: 20px; flex-wrap: wrap;'>
            <div style='flex: 1; min-width: 120px; background: #0d1b2a; border-radius: 8px; padding: 12px; text-align: center;'>
                <p style='color: #868e96; margin: 0; font-size: 11px;'>P&L Delta</p>
                <p style='color: {pnl_delta_color}; margin: 5px 0 0 0; font-size: 18px; font-weight: bold;'>{'+' if data['pnl_delta'] >= 0 else ''}${data['pnl_delta']:.2f}</p>
            </div>
            <div style='flex: 1; min-width: 120px; background: #0d1b2a; border-radius: 8px; padding: 12px; text-align: center;'>
                <p style='color: #868e96; margin: 0; font-size: 11px;'>Win Rate Delta</p>
                <p style='color: {wr_delta_color}; margin: 5px 0 0 0; font-size: 18px; font-weight: bold;'>{'+' if data['wr_delta'] >= 0 else ''}{data['wr_delta']:.1f}%</p>
            </div>
            <div style='flex: 1; min-width: 120px; background: #0d1b2a; border-radius: 8px; padding: 12px; text-align: center;'>
                <p style='color: #868e96; margin: 0; font-size: 11px;'>Trade Count Delta</p>
                <p style='color: #fff; margin: 5px 0 0 0; font-size: 18px; font-weight: bold;'>{data['trade_delta']:+d}</p>
            </div>
        </div>
    """
    
    # Beta tier breakdown
    tier_breakdown = data['beta_tier_breakdown']
    if beta['total_trades'] > 0:
        html += """
        <div style='margin-top: 20px;'>
            <h4 style='color: #adb5bd;'>Beta Bot Confidence Tier Distribution</h4>
            <div style='display: flex; gap: 8px; flex-wrap: wrap;'>
        """
        tier_colors = {"A": "#2b8a3e", "B": "#1971c2", "C": "#868e96", "D": "#d9480f", "F": "#c92a2a"}
        for tier in ["A", "B", "C", "D", "F"]:
            count = tier_breakdown.get(tier, 0)
            html += f"""
                <div style='background: {tier_colors[tier]}22; border: 1px solid {tier_colors[tier]}; border-radius: 4px; padding: 8px 12px; text-align: center;'>
                    <span style='color: {tier_colors[tier]}; font-weight: bold;'>{tier}-Tier</span>
                    <span style='color: #fff; margin-left: 5px;'>{count}</span>
                </div>
            """
        html += "</div></div>"
    
    html += "</div>"
    return html


def build_beta_learning_html():
    """Build HTML section for Beta bot's learning insights."""
    try:
        from src.beta_learning_system import BetaLearningSystem
        learner = BetaLearningSystem()
        summary = learner.get_learning_summary()
    except Exception as e:
        return f"<div class='section'><p style='color:#c92a2a;'>Beta learning data unavailable: {e}</p></div>"
    
    if not summary.get("trades_analyzed"):
        return "<div class='section'><h3>Beta Bot Learning</h3><p>Insufficient trading data for pattern analysis.</p></div>"
    
    html = """
    <div class='section' style='background: #1a1a2e; border-radius: 8px; padding: 15px; margin-top: 15px;'>
        <h3 style='color: #9c36b5; margin-top: 0;'>Beta Bot Learning Insights</h3>
    """
    
    html += f"<p><b>Data Analyzed:</b> {summary.get('trades_analyzed', 0)} trades</p>"
    
    inversion = summary.get("inversion_analysis", {})
    if inversion:
        inv_stats = inversion.get("inverted", {})
        norm_stats = inversion.get("normal", {})
        if inv_stats and norm_stats:
            inv_wr = inv_stats.get("win_rate", 0)
            inv_pnl = inv_stats.get("pnl", 0)
            norm_wr = norm_stats.get("win_rate", 0)
            norm_pnl = norm_stats.get("pnl", 0)
            
            inv_color = "#2b8a3e" if inv_pnl > norm_pnl else "#c92a2a"
            html += f"""
            <div style='display: flex; gap: 15px; margin: 10px 0; flex-wrap: wrap;'>
                <div style='flex: 1; min-width: 150px; background: #0d1b2a; border-radius: 6px; padding: 10px; border-left: 3px solid #da77f2;'>
                    <p style='color: #868e96; margin: 0; font-size: 11px;'>Inverted Signals (F-tier)</p>
                    <p style='color: {inv_color}; margin: 3px 0; font-size: 16px; font-weight: bold;'>${inv_pnl:.2f}</p>
                    <p style='color: #adb5bd; margin: 0; font-size: 11px;'>{inv_wr:.1f}% WR</p>
                </div>
                <div style='flex: 1; min-width: 150px; background: #0d1b2a; border-radius: 6px; padding: 10px; border-left: 3px solid #4dabf7;'>
                    <p style='color: #868e96; margin: 0; font-size: 11px;'>Normal Signals (A-D tier)</p>
                    <p style='color: #fff; margin: 3px 0; font-size: 16px; font-weight: bold;'>${norm_pnl:.2f}</p>
                    <p style='color: #adb5bd; margin: 0; font-size: 11px;'>{norm_wr:.1f}% WR</p>
                </div>
            </div>
            """
    
    tier_perf = summary.get("tier_performance", {})
    if tier_perf:
        html += "<h4 style='color: #adb5bd; margin-top: 15px;'>Performance by Tier</h4>"
        html += "<table style='width: 100%; border: none;'><tr style='background: #2d3748;'><th style='color: #fff; border: none; padding: 6px;'>Tier</th><th style='color: #fff; border: none; padding: 6px;'>Trades</th><th style='color: #fff; border: none; padding: 6px;'>Win Rate</th><th style='color: #fff; border: none; padding: 6px;'>P&L</th></tr>"
        tier_colors = {"A": "#2b8a3e", "B": "#1971c2", "C": "#868e96", "D": "#d9480f", "F": "#c92a2a"}
        for tier in ["A", "B", "C", "D", "F"]:
            if tier in tier_perf:
                stats = tier_perf[tier]
                pnl_color = "#2b8a3e" if stats.get("pnl", 0) >= 0 else "#c92a2a"
                html += f"<tr><td style='border: none; padding: 5px; color: {tier_colors[tier]}; font-weight: bold;'>{tier}</td>"
                html += f"<td style='border: none; padding: 5px; color: #fff;'>{stats.get('trades', 0)}</td>"
                html += f"<td style='border: none; padding: 5px; color: #fff;'>{stats.get('win_rate', 0):.1f}%</td>"
                html += f"<td style='border: none; padding: 5px; color: {pnl_color};'>${stats.get('pnl', 0):.2f}</td></tr>"
        html += "</table>"
    
    recommendations = summary.get("recommendations", [])
    if recommendations:
        html += "<h4 style='color: #adb5bd; margin-top: 15px;'>Beta Learning Recommendations</h4><ul style='color: #fff; margin: 0; padding-left: 20px;'>"
        for rec in recommendations[:5]:
            rec_type = rec.get("type", "")
            icon = "&#10003;" if "promote" in rec_type else "&#10007;" if "block" in rec_type else "&#9432;"
            color = "#2b8a3e" if "promote" in rec_type else "#c92a2a" if "block" in rec_type else "#4dabf7"
            html += f"<li style='margin: 5px 0;'><span style='color: {color};'>{icon}</span> {rec.get('action', '')}</li>"
        html += "</ul>"
    
    html += "</div>"
    return html


def load_learning_intelligence():
    """Load comprehensive learning analysis data for email report."""
    analysis = _read_json(COMPREHENSIVE_ANALYSIS_PATH, default={})
    rules = _read_json(DAILY_LEARNING_RULES_PATH, default={})
    feedback = _read_json(FEEDBACK_SUMMARY_PATH, default={})
    
    return {
        "analysis": analysis,
        "rules": rules,
        "feedback": feedback,
        "profitable_patterns": analysis.get("profitable_patterns", [])[:10],
        "losing_patterns": analysis.get("losing_patterns", [])[:10],
        "high_potential": analysis.get("high_potential_patterns", [])[:5],
        "symbol_biases": rules.get("symbol_biases", {}),
        "timing_rules": rules.get("timing_rules", {}),
        "regime_rules": rules.get("regime_rules", {}),
        "direction_accuracy": feedback.get("direction_accuracy", 0),
        "early_exit_rate": feedback.get("early_exit_rate", 0),
        "timing_patterns": feedback.get("timing_patterns", [])
    }


def build_learning_intelligence_html():
    """Build HTML section for learning intelligence insights."""
    data = load_learning_intelligence()
    
    html = "<div class='section'><h2>Learning Intelligence Summary</h2>"
    
    analysis = data.get("analysis", {})
    data_summary = analysis.get("data_summary", {})
    dir_acc = data.get('direction_accuracy', 0)
    if dir_acc > 1: dir_acc = dir_acc / 100  
    early_exit = data.get('early_exit_rate', 0)
    if early_exit > 1: early_exit = early_exit / 100
    
    html += f"""
        <p><b>Data Analyzed:</b> {data_summary.get('total', 0)} records 
        ({data_summary.get('executed', 0)} executed, {data_summary.get('missed', 0)} missed, 
        {data_summary.get('blocked', 0)} blocked)</p>
        <p><b>Direction Accuracy:</b> {dir_acc:.1%} | 
        <b>Early Exit Rate:</b> {early_exit:.1%}</p>
    """
    
    profitable = data.get("profitable_patterns", [])
    if profitable:
        html += "<h3 style='color:#2b8a3e;'>Profitable Patterns (Auto-Applied)</h3>"
        html += "<table><tr><th>Pattern</th><th>P&L</th><th>Win Rate</th><th>Trades</th><th>EV</th></tr>"
        for p in profitable[:8]:
            pattern = p.get('pattern', '')[:50]
            html += f"<tr><td>{pattern}</td><td class='ok'>${p.get('pnl', 0):.2f}</td>"
            html += f"<td>{p.get('wr', 0):.1f}%</td><td>{p.get('trades', 0)}</td><td>${p.get('ev', 0):.4f}</td></tr>"
        html += "</table>"
    
    losing = data.get("losing_patterns", [])
    if losing:
        html += "<h3 style='color:#c92a2a;'>Losing Patterns (Auto-Blocked)</h3>"
        html += "<table><tr><th>Pattern</th><th>P&L</th><th>Win Rate</th><th>Trades</th></tr>"
        for p in losing[:6]:
            pattern = p.get('pattern', '')[:50]
            html += f"<tr><td>{pattern}</td><td class='bad'>${p.get('pnl', 0):.2f}</td>"
            html += f"<td class='bad'>{p.get('wr', 0):.1f}%</td><td>{p.get('trades', 0)}</td></tr>"
        html += "</table>"
    
    biases = data.get("symbol_biases", {})
    if biases:
        html += "<h3>Symbol Direction Biases</h3>"
        html += "<table><tr><th>Symbol</th><th>Preferred Direction</th><th>Advantage</th></tr>"
        sorted_biases = sorted(biases.items(), key=lambda x: x[1].get('advantage', 0), reverse=True)
        for sym, bias in sorted_biases[:10]:
            dir_class = 'ok' if bias.get('preferred_direction') == 'LONG' else 'warn'
            html += f"<tr><td>{sym}</td><td class='{dir_class}'>{bias.get('preferred_direction', '-')}</td>"
            html += f"<td>${bias.get('advantage', 0):.2f}</td></tr>"
        html += "</table>"
    
    timing = data.get("timing_rules", {})
    if timing:
        html += "<h3>Timing Insights</h3><ul>"
        if timing.get("best_sessions"):
            html += f"<li><b>Best Sessions:</b> {', '.join(timing.get('best_sessions', [])[:3])}</li>"
        if timing.get("avoid_sessions"):
            avoid = [s for s in timing.get("avoid_sessions", []) if s not in timing.get("best_sessions", [])]
            if avoid:
                html += f"<li><b>Avoid Sessions:</b> {', '.join(avoid[:2])}</li>"
        if timing.get("best_days"):
            html += f"<li><b>Best Days:</b> {', '.join(timing.get('best_days', [])[:3])}</li>"
        html += "</ul>"
    
    high_potential = data.get("high_potential", [])
    if high_potential:
        html += "<h3>High Potential Patterns (Near Profitable)</h3>"
        html += "<table><tr><th>Pattern</th><th>R:R</th><th>WR Gap</th><th>Trades</th></tr>"
        for p in high_potential[:5]:
            pattern = p.get('pattern', '')[:40]
            html += f"<tr><td>{pattern}</td><td>{p.get('rr', 0):.2f}</td>"
            html += f"<td>{p.get('wr_gap', 0):.1f}%</td><td>{p.get('trades', 0)}</td></tr>"
        html += "</table>"
    
    html += "</div>"
    return html

# --------------------------------------------------------------------------------------
# Helpers to compute metrics and simple SVG charts
# --------------------------------------------------------------------------------------

def metrics_from_assets(assets):
    wrs = [a["metrics"].get("win_rate", 0.5) for a in assets]
    pfs = [a["metrics"].get("profit_factor", 1.2) for a in assets]
    evs = [a["metrics"].get("expectancy", 0.0) for a in assets]
    return {
        "avg_wr": round(mean(wrs) if wrs else 0.5, 4),
        "avg_pf": round(mean(pfs) if pfs else 1.2, 4),
        "avg_ev": round(mean(evs) if evs else 0.0, 6)
    }

TRADES_FUTURES_FILE = os.path.join(LOG_DIR, "trades_futures.json")

def compute_daily_pnl(per_trade_logs_by_asset=None):
    """
    Compute daily P&L from actual trade data.
    Uses logs/trades_futures.json as the canonical source.
    """
    total = 0.0
    per_asset = {}
    
    trades_data = _read_json(TRADES_FUTURES_FILE, default={"trades": []})
    trades = trades_data.get("trades", [])
    
    if not trades:
        return 0.0, {}
    
    now = _now()
    day_ago = now - 86400
    
    for trade in trades:
        close_ts = trade.get("close_ts") or trade.get("ts", 0)
        if close_ts < day_ago:
            continue
        
        symbol = trade.get("symbol", "UNKNOWN")
        net_pnl = trade.get("net_pnl", 0) or 0
        
        per_asset[symbol] = per_asset.get(symbol, 0.0) + net_pnl
        total += net_pnl
    
    return round(total, 2), {k: round(v, 2) for k, v in per_asset.items()}

def svg_bar_chart(title, series, width=600, height=200, margin=40):
    # series: list of (label, value)
    max_val = max([abs(v) for _, v in series]) if series else 1.0
    bar_w = max(10, (width - 2*margin) // max(1,len(series)))
    svg = [f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">']
    svg.append(f'<text x="{margin}" y="20" font-size="14" font-family="Arial" fill="#333">{title}</text>')
    # Axis
    svg.append(f'<line x1="{margin}" y1="{height - margin}" x2="{width - margin}" y2="{height - margin}" stroke="#999" stroke-width="1"/>')
    # Bars
    for i, (label, val) in enumerate(series):
        x = margin + i*bar_w + 4
        h = 0 if max_val==0 else int(((abs(val))/max_val) * (height - 2*margin))
        y = (height - margin) - h if val >= 0 else (height - margin)
        color = "#2b8a3e" if val >= 0 else "#c92a2a"
        svg.append(f'<rect x="{x}" y="{y}" width="{bar_w-8}" height="{h}" fill="{color}"/>')
        svg.append(f'<text x="{x}" y="{height - margin + 12}" font-size="10" font-family="Arial" fill="#555" transform="rotate(0 {x},{height - margin + 12})">{label}</text>')
    svg.append("</svg>")
    return "\n".join(svg)

def svg_line_chart(title, points, width=600, height=200, margin=40):
    # points: list of float values (time-ordered)
    if not points:
        return svg_bar_chart(title, [], width, height, margin)
    max_v = max(points); min_v = min(points)
    rng = max(1e-9, max_v - min_v)
    x_step = (width - 2*margin) / max(1, len(points)-1)
    path = []
    for i, v in enumerate(points):
        x = margin + i*x_step
        y = height - margin - ((v - min_v) / rng) * (height - 2*margin)
        path.append(f"{x},{y}")
    svg = [f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">']
    svg.append(f'<text x="{margin}" y="20" font-size="14" font-family="Arial" fill="#333">{title}</text>')
    svg.append(f'<polyline fill="none" stroke="#1c7ed6" stroke-width="2" points="{" ".join(path)}"/>')
    svg.append(f'<line x1="{margin}" y1="{height - margin}" x2="{width - margin}" y2="{height - margin}" stroke="#999" stroke-width="1"/>')
    svg.append("</svg>")
    return "\n".join(svg)

# --------------------------------------------------------------------------------------
# Email composition
# --------------------------------------------------------------------------------------

def build_html_report():
    # Core data
    registry = _read_json(REGISTRY_PATH, default={"assets": {}})
    applied = _read_json(INTRA_APPLIED_PATH, default={"assets": {}})
    venue24h = _read_json(VENUE_24H_PATH, default={})
    tag_audits = _read_jsonl(TAG_AUDIT_LOG, limit=200)
    attr_snaps = _read_jsonl(ATTR_LOG, limit=200)
    ultra_logs = _read_jsonl(ULTRA_LOG, limit=100)
    promoter_logs = _read_jsonl(PROMOTER_LOG, limit=100)
    scheduler_logs = _read_jsonl(SCHED_LOG, limit=200)
    uplift_logs = _read_jsonl(UPLIFT_LOG, limit=200)
    intraday_engine_logs = _read_jsonl(INTRADAY_ENGINE_LOG, limit=200)
    profit_push_logs = _read_jsonl(PROFIT_PUSH_LOG, limit=100)

    # Portfolio metrics from the latest multi_asset_summary available in recent logs (fallback)
    latest_ultra = ultra_logs[-1] if ultra_logs else {}
    latest_baseline = latest_ultra.get("audit", {}).get("portfolio_base", {"wr":0.55,"pf":1.45,"ev":0.001})
    latest_floors = latest_ultra.get("audit", {}).get("floors", {})
    decisions = latest_ultra.get("audit", {}).get("decisions", [])

    # Daily PnL
    total_pnl, pnl_by_asset = compute_daily_pnl()

    # Bar chart: PnL by asset
    pnl_series = [(a, pnl_by_asset.get(a, 0.0)) for a in ASSETS]
    pnl_chart = svg_bar_chart("Daily P&L by Asset", pnl_series)

    # Line chart: portfolio WR over last N logs (approximate)
    wr_points = []
    for item in ultra_logs[-30:]:
        pb = item.get("audit", {}).get("portfolio_base", {})
        wr_points.append(pb.get("wr", None))
    wr_points = [p for p in wr_points if p is not None]
    wr_chart = svg_line_chart("Portfolio Win Rate (last 30 cycles)", wr_points)

    # Tag coverage (latest)
    tag_latest = tag_audits[-1] if tag_audits else {}
    tag_report = tag_latest.get("report", {}) if isinstance(tag_latest.get("report"), dict) else {}
    tag_blocklist = tag_latest.get("blocklist", []) if isinstance(tag_latest.get("blocklist"), list) else []

    # Canary outcomes (operators_consolidation wrote them)
    canary_outcomes = []
    for ev in tag_audits[::-1]:
        if ev.get("event") == "canary_monitor_and_retry":
            canary_outcomes = ev.get("outcomes", [])
            break

    # Venue profiles summary (last_profile per key)
    venue_rows = []
    for key, bucket in venue24h.items():
        lp = bucket.get("last_profile", {})
        venue_rows.append({
            "key": key,
            "mode": lp.get("mode"),
            "slice": lp.get("slice_parts"),
            "delay": lp.get("delay_ms"),
            "vol_band": bucket.get("vol_band")
        })

    # Signal attribution (best per asset)
    sig_latest = attr_snaps[-1] if attr_snaps else {}
    signal_highlights = []
    for asset, pkt in (sig_latest.get("assets", {}) or {}).items():
        sigs = pkt.get("signals", {}) or {}
        if not sigs: continue
        best = sorted(sigs.items(), key=lambda kv: kv[1].get("ev", 0.0), reverse=True)[0]
        signal_highlights.append({"asset": asset, "signal": best[0], **best[1]})

    # Applied overrides quick view
    applied_rows = []
    for a, pkt in (applied.get("assets", {}) or {}).items():
        applied_rows.append({
            "asset": a,
            "scale": pkt.get("position_scale"),
            "router": pkt.get("execution_router", {}).get("mode"),
            "hold_orders": pkt.get("execution_router", {}).get("hold_orders"),
            "swap": pkt.get("mid_session_swap"),
        })

    # Compile HTML
    styles = """
        <style>
          body { font-family: Arial, sans-serif; color: #222; }
          h1,h2 { color: #0b7285; }
          .section { margin-bottom: 24px; }
          table { border-collapse: collapse; width: 100%; }
          th, td { border: 1px solid #ddd; padding: 8px; font-size: 13px; }
          th { background: #f1f3f5; text-align: left; }
          .ok { color: #2b8a3e; }
          .warn { color: #d9480f; }
          .bad { color: #c92a2a; }
          .chart { margin: 8px 0 16px 0; }
          .small { font-size: 12px; color: #555; }
        </style>
    """
    header = f"<h1>Nightly Report – Autonomous Crypto Desk</h1><div class='small'>Timestamp: {_ts()}</div>"
    overview = f"""
      <div class='section'>
        <h2>Portfolio overview</h2>
        <p><b>Average WR:</b> {latest_baseline.get('wr', 0):.2%} &nbsp; | &nbsp;
           <b>Average PF:</b> {latest_baseline.get('pf', 0):.2f} &nbsp; | &nbsp;
           <b>Average EV:</b> {latest_baseline.get('ev', 0):.6f}</p>
        <p><b>Daily P&L:</b> {total_pnl:.6f}</p>
        <div class='chart'>{pnl_chart}</div>
        <div class='chart'>{wr_chart}</div>
        <p class='small'>Floors (variance-aware): WR≥{latest_floors.get('wr_floor','—')}, PF≥{latest_floors.get('pf_floor','—')}, EV>0</p>
      </div>
    """

    tag_html = "<div class='section'><h2>Tag coverage health</h2><table><tr><th>Asset</th><th>Untagged %</th><th>Trades</th><th>Status</th></tr>"
    for asset, info in sorted(tag_report.items(), key=lambda kv: kv[1]["untagged_pct"], reverse=True):
        pct = info["untagged_pct"]
        status = ("bad" if pct>0.03 else "warn") if pct>0.02 else "ok"
        tag_html += f"<tr><td>{asset}</td><td>{pct:.2%}</td><td>{info['n']}</td><td class='{status}'>{status.upper()}</td></tr>"
    tag_html += "</table>"
    if tag_blocklist:
        tag_html += f"<p class='bad'><b>Blocklisted for uplift-dependent actions:</b> {', '.join(tag_blocklist)}</p>"
    tag_html += "</div>"

    canary_html = "<div class='section'><h2>Canary outcomes</h2><table><tr><th>Asset</th><th>Result</th><th>Reason</th></tr>"
    for oc in canary_outcomes or []:
        cls = "ok" if oc.get("result")=="PASS" else "bad"
        canary_html += f"<tr><td>{oc.get('asset')}</td><td class='{cls}'>{oc.get('result')}</td><td>{oc.get('reason','—')}</td></tr>"
    if not canary_outcomes:
        canary_html += "<tr><td colspan='3' class='small'>No canary events recorded in the last cycle.</td></tr>"
    canary_html += "</table></div>"

    venue_html = "<div class='section'><h2>Venue profile changes (24h)</h2><table><tr><th>Asset::Venue</th><th>Mode</th><th>Slice parts</th><th>Delay ms</th><th>Vol band</th></tr>"
    for row in venue_rows[:25]:
        venue_html += f"<tr><td>{row['key']}</td><td>{row['mode']}</td><td>{row['slice']}</td><td>{row['delay']}</td><td>{row['vol_band']}</td></tr>"
    venue_html += "</table></div>"

    applied_html = "<div class='section'><h2>Applied intraday overrides</h2><table><tr><th>Asset</th><th>Scale</th><th>Router</th><th>Hold orders</th><th>Mid-session swap</th></tr>"
    for row in sorted(applied_rows, key=lambda x: x["asset"]):
        applied_html += f"<tr><td>{row['asset']}</td><td>{row['scale']}</td><td>{row['router']}</td><td>{row['hold_orders']}</td><td>{row['swap']}</td></tr>"
    applied_html += "</table></div>"

    signals_html = "<div class='section'><h2>Signal attribution highlights</h2><table><tr><th>Asset</th><th>Signal</th><th>WR</th><th>PF</th><th>EV</th></tr>"
    for s in signal_highlights:
        signals_html += f"<tr><td>{s['asset']}</td><td>{s['signal']}</td><td>{s.get('wr',0.0):.2%}</td><td>{s.get('pf',0.0):.2f}</td><td>{s.get('ev',0.0):.6f}</td></tr>"
    if not signal_highlights:
        signals_html += "<tr><td colspan='5' class='small'>No signal snapshots available.</td></tr>"
    signals_html += "</table></div>"

    audits_html = "<div class='section'><h2>Audit summary</h2><ul>"
    audits_html += f"<li><b>Logs inspected:</b> ultra_uplift_unified, intraday_uplift, relative_uplift_promoter, intraday_engine, intraday_scheduler, operators_consolidation, profit_push_engine</li>"
    audits_html += f"<li><b>Decisions last cycle:</b> {len(decisions)}</li>"
    audits_html += "</ul></div>"

    learning_html = build_learning_intelligence_html()
    dual_bot_html = build_dual_bot_comparison_html()
    beta_learning_html = build_beta_learning_html()

    html = f"<!doctype html><html><head>{styles}</head><body>{header}{dual_bot_html}{beta_learning_html}{overview}{learning_html}{tag_html}{canary_html}{venue_html}{applied_html}{signals_html}{audits_html}</body></html>"
    return html

def send_email_html(subject, html_body):
    # EMAIL ALERTS DISABLED - user requested no more emails
    print(f"   ℹ️ Email disabled - would have sent: {subject[:50]}...")
    return
    
    to_email = os.environ.get("REPORT_TO_EMAIL", "mlevitan96@gmail.com")
    smtp_user = os.environ.get("SMTP_USER", to_email)
    smtp_pass = os.environ.get("SMTP_PASS", "")
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = smtp_user
    msg['To'] = to_email
    msg.attach(MIMEText(html_body, 'html'))

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(msg['From'], [msg['To']], msg.as_string())

def send_nightly_email_report():
    subject = f"[Nightly] Autonomous Crypto Desk — 24h Report ({_ts()})"
    html = build_html_report()
    send_email_html(subject, html)
    print("Nightly email sent.")

# --------------------------------------------------------------------------------------
# CLI quick run – build and print HTML (won’t send without SMTP creds)
# --------------------------------------------------------------------------------------

if __name__ == "__main__":
    # Preview mode: prints the HTML to stdout. Set SEND=1 to actually send via SMTP with env vars.
    html = build_html_report()
    print(html[:1000] + "\n...\n")  # preview head
    if os.environ.get("SEND","0") == "1":
        send_nightly_email_report()