# src/nightly_email_report_v2.py
#
# Nightly Email Report (Executive-grade) – Clear dollar P&L, color-coded winners/losers,
# 7-day P&L trend, plain-language summary (2–4 sentences), learning highlights,
# and concise operator notes. Runs immediately after the full nightly pipeline.
#
# How this differs from v1:
#   - Dollar P&L with green/red color coding and simple layout
#   - 7-day cumulative P&L line chart
#   - Executive Summary: 2–4 sentences in plain language
#   - "What the system learned today" and Operator Notes in concise bullets
#   - Cleaner tables and typography for readability
#
# SMTP env (set these in your environment/secrets):
#   REPORT_TO_EMAIL=mlevitan96@gmail.com
#   SMTP_USER=your_smtp_username_or_email
#   SMTP_PASS=your_smtp_password (e.g., Replit secret)
#   SMTP_HOST=smtp.gmail.com
#   SMTP_PORT=587
#
# Integration:
#   Call send_nightly_email_report_v2() at the end of your nightly pipeline.

import os, json, time, smtplib, math
from statistics import mean
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

CONFIG_DIR = "configs"
LOG_DIR = "logs"

REGISTRY_PATH = os.path.join(CONFIG_DIR, "strategy_registry.json")
INTRA_APPLIED_PATH = os.path.join(CONFIG_DIR, "intraday_applied.json")
VENUE_24H_PATH = os.path.join(CONFIG_DIR, "venue_profiles_24h.json")

OPERATORS_LOG = os.path.join(LOG_DIR, "operators_consolidation.jsonl")
ULTRA_LOG = os.path.join(LOG_DIR, "ultra_uplift_unified.jsonl")
UPLIFT_LOG = os.path.join(LOG_DIR, "intraday_uplift.jsonl")
ENGINE_LOG = os.path.join(LOG_DIR, "intraday_engine.jsonl")
SCHED_LOG = os.path.join(LOG_DIR, "intraday_scheduler.jsonl")
TRADES_FUTURES_FILE = os.path.join(LOG_DIR, "trades_futures.json")
FEEDBACK_LOOP_FILE = "feature_store/feedback_loop_summary.json"
DAILY_LEARNER_FILE = "feature_store/optimal_thresholds.json"

ASSETS = ["BTCUSDT","ETHUSDT","SOLUSDT","AVAXUSDT","DOTUSDT","TRXUSDT","XRPUSDT","ADAUSDT","DOGEUSDT","BNBUSDT","MATICUSDT"]

def _ts(): return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
def _read_json(path, default=None):
    if not os.path.exists(path): return default
    try:
        with open(path,"r") as f: return json.load(f)
    except: return default

def _read_jsonl(path, limit=1000):
    items = []
    if not os.path.exists(path): return items
    try:
        with open(path,"r") as f:
            for line in f:
                line=line.strip()
                if not line: continue
                try: items.append(json.loads(line))
                except: continue
    except: pass
    return items[-limit:]

def portfolio_baseline():
    trades_data = _read_json(TRADES_FUTURES_FILE, default={"trades": []})
    trades = trades_data.get("trades", [])
    if not trades:
        return {"wr": 0.0, "pf": 1.0, "ev": 0.0, "total_trades": 0, "avg_size": 0.0}
    
    wins = sum(1 for t in trades if t.get("net_pnl", 0) > 0)
    total_pnl = sum(t.get("net_pnl", 0) for t in trades)
    avg_size = sum(t.get("margin_collateral", 0) for t in trades) / len(trades) if trades else 0
    
    win_pnl = sum(t.get("net_pnl", 0) for t in trades if t.get("net_pnl", 0) > 0)
    loss_pnl = abs(sum(t.get("net_pnl", 0) for t in trades if t.get("net_pnl", 0) < 0))
    
    return {
        "wr": wins / len(trades) if trades else 0,
        "pf": win_pnl / loss_pnl if loss_pnl > 0 else 1.0,
        "ev": total_pnl / len(trades) if trades else 0,
        "total_trades": len(trades),
        "avg_size": avg_size
    }

def compute_daily_pnl():
    from datetime import datetime, timedelta
    trades_data = _read_json(TRADES_FUTURES_FILE, default={"trades": []})
    trades = trades_data.get("trades", [])
    
    today = datetime.now().strftime('%Y-%m-%d')
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    
    today_trades = [t for t in trades if t.get('timestamp', '').startswith(today)]
    yesterday_trades = [t for t in trades if t.get('timestamp', '').startswith(yesterday)]
    
    target_trades = today_trades if today_trades else yesterday_trades
    
    total = sum(t.get("net_pnl", 0) for t in target_trades)
    per_asset = {}
    for t in target_trades:
        symbol = t.get("symbol", "UNKNOWN")
        per_asset[symbol] = per_asset.get(symbol, 0) + t.get("net_pnl", 0)
    
    return total, per_asset

def compute_7day_pnl_series():
    from datetime import datetime, timedelta
    trades_data = _read_json(TRADES_FUTURES_FILE, default={"trades": []})
    trades = trades_data.get("trades", [])
    
    buckets = {}
    for i in range(7):
        day = (datetime.now() - timedelta(days=6-i)).strftime('%Y-%m-%d')
        buckets[day] = 0.0
    
    for t in trades:
        ts = t.get("timestamp", "")[:10]
        if ts in buckets:
            buckets[ts] += t.get("net_pnl", 0)
    
    days_sorted = sorted(buckets.items())
    cum = []
    acc = 0.0
    for _, val in days_sorted:
        acc += val
        cum.append(acc)
    
    return cum[-7:] if len(cum) >= 7 else [0.0] * (7 - len(cum)) + cum

def get_learning_summary():
    feedback = _read_json(FEEDBACK_LOOP_FILE, default={})
    learner = _read_json(DAILY_LEARNER_FILE, default={})
    
    return {
        "direction_accuracy": feedback.get("direction_accuracy"),
        "early_exit_rate": feedback.get("early_exit_rate"),
        "timing_patterns_learned": feedback.get("timing_patterns_learned"),
        "recommendations": feedback.get("recommendations", []),
        "profitable_patterns": learner.get("profitable_patterns", [])[:5],
        "high_potential_patterns": learner.get("high_potential_patterns", [])[:5],
        "ofi_optimal": learner.get("ofi_threshold_optimal"),
        "last_run": feedback.get("timestamp")
    }

def latest_tag_audit():
    ops = _read_jsonl(OPERATORS_LOG, limit=300)
    for item in reversed(ops):
        if item.get("event") == "tag_coverage_audit":
            return item.get("report", {}), set(item.get("blocklist", []))
    return {}, set()

def latest_canary_outcomes():
    ops = _read_jsonl(OPERATORS_LOG, limit=300)
    for item in reversed(ops):
        if item.get("event") == "canary_monitor_and_retry":
            return item.get("outcomes", [])
    return []

def venue_profiles_snapshot():
    v = _read_json(VENUE_24H_PATH, default={})
    rows = []
    for key, bucket in v.items():
        lp = bucket.get("last_profile", {})
        rows.append({
            "key": key,
            "mode": lp.get("mode"),
            "slice": lp.get("slice_parts"),
            "delay": lp.get("delay_ms"),
            "vol_band": bucket.get("vol_band")
        })
    return rows

def applied_overrides_snapshot():
    applied = _read_json(INTRA_APPLIED_PATH, default={"assets": {}})
    rows = []
    for a, pkt in (applied.get("assets", {}) or {}).items():
        rows.append({
            "asset": a,
            "scale": pkt.get("position_scale"),
            "router": pkt.get("execution_router", {}).get("mode"),
            "hold_orders": pkt.get("execution_router", {}).get("hold_orders"),
            "swap": pkt.get("mid_session_swap")
        })
    return rows

def svg_line_chart(title, points, width=640, height=220, margin=40):
    if not points: points = [0,0,0,0,0,0,0]
    max_v = max(points); min_v = min(points); rng = max(1e-9, max_v-min_v)
    x_step = (width - 2*margin) / max(1, len(points)-1)
    path = []
    for i, v in enumerate(points):
        x = margin + i*x_step
        y = height - margin - ((v - min_v) / rng) * (height - 2*margin)
        path.append(f"{x},{y}")
    svg = [f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">']
    svg.append(f'<text x="{margin}" y="20" font-size="14" font-family="Arial" fill="#333">{title}</text>')
    svg.append(f'<polyline fill="none" stroke="#12b886" stroke-width="2.5" points="{" ".join(path)}"/>')
    svg.append(f'<line x1="{margin}" y1="{height - margin}" x2="{width - margin}" y2="{height - margin}" stroke="#999" stroke-width="1"/>')
    svg.append("</svg>")
    return "\n".join(svg)

def build_executive_summary(total_pnl_usd, top_winners, top_losers, base, learning):
    summary = []
    pnl_str = f"${abs(total_pnl_usd):.2f}"
    if total_pnl_usd >= 0:
        summary.append(f"We closed the day up {pnl_str}.")
    else:
        summary.append(f"We closed the day down {pnl_str}.")

    if top_winners:
        winners_str = ", ".join([f"{a.split('USDT')[0]} (+${abs(v):.2f})" for a, v in top_winners])
        summary.append(f"Strength came from {winners_str}.")
    if top_losers:
        losers_str = ", ".join([f"{a.split('USDT')[0]} (-${abs(v):.2f})" for a, v in top_losers])
        summary.append(f"Weakness was led by {losers_str}.")

    wr_pct = f"{base['wr']*100:.1f}%"
    avg_size = f"${base.get('avg_size', 0):.2f}"
    total_trades = base.get('total_trades', 0)
    summary.append(f"Win rate: {wr_pct} across {total_trades} total trades (avg size: {avg_size}).")
    
    dir_acc = learning.get("direction_accuracy")
    if dir_acc:
        summary.append(f"Direction accuracy: {dir_acc:.1f}%.")

    return " ".join(summary)

def build_email_html():
    base = portfolio_baseline()
    total_pnl_usd, pnl_by_asset = compute_daily_pnl()
    learning = get_learning_summary()

    winners = sorted([(a, v) for a, v in pnl_by_asset.items() if v > 0], key=lambda kv: kv[1], reverse=True)[:3]
    losers = sorted([(a, v) for a, v in pnl_by_asset.items() if v < 0], key=lambda kv: kv[1])[:3]

    series7 = compute_7day_pnl_series()
    chart7 = svg_line_chart("7-Day Cumulative P&L ($)", series7)

    tag_report, tag_blocklist = latest_tag_audit()
    canary_outcomes = latest_canary_outcomes()
    notable_canary = any(x.get("result") == "PASS" for x in canary_outcomes)

    venue_rows = venue_profiles_snapshot()[:15]
    overrides_rows = applied_overrides_snapshot()

    summary_text = build_executive_summary(total_pnl_usd, winners, losers, base, learning)

    styles = """
    <style>
      body { font-family: Arial, Helvetica, sans-serif; color: #222; margin: 0; padding: 0; }
      .wrap { max-width: 900px; margin: 0 auto; padding: 24px; }
      h1 { margin: 0 0 4px; color: #0b7285; }
      h2 { margin: 20px 0 8px; color: #0b7285; }
      .subtitle { color: #666; margin-bottom: 16px; }
      .summary { background: #f8f9fa; border: 1px solid #e9ecef; padding: 12px 16px; border-radius: 8px; line-height: 1.4; }
      .pill { display: inline-block; padding: 6px 10px; border-radius: 18px; font-weight: bold; }
      .pill-green { background: #d3f9d8; color: #2b8a3e; border: 1px solid #b2f2bb; }
      .pill-red { background: #ffe3e3; color: #c92a2a; border: 1px solid #ffa8a8; }
      .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
      table { border-collapse: collapse; width: 100%; }
      th, td { border: 1px solid #ddd; padding: 8px; font-size: 13px; }
      th { background: #f1f3f5; text-align: left; }
      .ok { color: #2b8a3e; }
      .warn { color: #d9480f; }
      .bad { color: #c92a2a; }
      .chart { margin: 8px 0 16px 0; }
      .section { margin-top: 18px; }
      .small { font-size: 12px; color: #666; }
    </style>
    """

    header = f"""
      <h1>Nightly Report — Autonomous Crypto Desk</h1>
      <div class="subtitle">Timestamp: {_ts()}</div>
      <div class="summary">{summary_text}</div>
    """

    pnl_pill = f"""
      <div class="section">
        <h2>Daily P&L</h2>
        <div>
          <span class="pill {'pill-green' if total_pnl_usd >= 0 else 'pill-red'}">
            Total: {'+$' if total_pnl_usd>=0 else '-$'}{abs(total_pnl_usd):.2f}
          </span>
          <span style="margin-left:10px;">WR: {base['wr']*100:.1f}% | Avg Size: ${base.get('avg_size', 0):.2f} | Trades: {base.get('total_trades', 0)}</span>
        </div>
      </div>
    """

    wl_html = "<div class='grid'>"
    wl_html += "<div><h2>Top performers</h2><table><tr><th>Asset</th><th>P&L (USD)</th></tr>"
    if winners:
        for a, v in winners:
            wl_html += f"<tr><td>{a}</td><td class='ok'>+${abs(v):.2f}</td></tr>"
    else:
        wl_html += "<tr><td colspan='2' class='small'>No winners today.</td></tr>"
    wl_html += "</table></div>"
    wl_html += "<div><h2>Underperformers</h2><table><tr><th>Asset</th><th>P&L (USD)</th></tr>"
    if losers:
        for a, v in losers:
            wl_html += f"<tr><td>{a}</td><td class='bad'>-${abs(v):.2f}</td></tr>"
    else:
        wl_html += "<tr><td colspan='2' class='small'>No losses today.</td></tr>"
    wl_html += "</table></div></div>"

    chart_html = f"<div class='section chart'>{chart7}</div>"

    learned = "<div class='section'><h2>What the system learned today</h2><ul>"
    
    dir_acc = learning.get("direction_accuracy")
    if dir_acc:
        learned += f"<li><b>Direction Accuracy:</b> {dir_acc:.1f}% of trades went in the profitable direction.</li>"
    
    early_exit = learning.get("early_exit_rate")
    if early_exit:
        learned += f"<li><b>Exit Timing:</b> {early_exit:.0f}% of exits were too early (before optimal profit).</li>"
    
    timing_patterns = learning.get("timing_patterns_learned")
    if timing_patterns:
        learned += f"<li><b>Timing Patterns:</b> Learned {timing_patterns} optimal hold duration patterns.</li>"
    
    profitable_patterns = learning.get("profitable_patterns", [])
    if profitable_patterns:
        top_pattern = profitable_patterns[0] if profitable_patterns else {}
        pattern_name = top_pattern.get("pattern", "Unknown")
        pattern_ev = top_pattern.get("ev", 0)
        learned += f"<li><b>Best Pattern:</b> {pattern_name} with EV ${pattern_ev:.2f}/trade.</li>"
    
    recommendations = learning.get("recommendations", [])
    if recommendations:
        rec = recommendations[0]
        learned += f"<li><b>Recommendation:</b> {rec.get('action', 'No action needed')}</li>"
    
    if "<li>" not in learned:
        learned += "<li><b>Steady State:</b> Accumulating data for pattern learning.</li>"
        learned += "<li><b>Governance:</b> Monitoring watchdogs active; awaiting sustained evidence before adjustments.</li>"
    
    learned += "</ul></div>"

    tag_html = "<div class='section'><h2>Operator notes</h2>"
    tag_html += "<h3 style='margin:6px 0;'>Tag coverage</h3><table><tr><th>Asset</th><th>Untagged %</th><th>Trades</th><th>Status</th></tr>"
    for asset, info in sorted(tag_report.items(), key=lambda kv: kv[1]["untagged_pct"], reverse=True):
        pct = info["untagged_pct"]
        status = ("bad" if pct>0.03 else "warn") if pct>0.02 else "ok"
        tag_html += f"<tr><td>{asset}</td><td>{pct:.2%}</td><td>{info['n']}</td><td class='{status}'>{status.upper()}</td></tr>"
    tag_html += "</table>"
    if tag_blocklist:
        tag_html += f"<p class='bad small'><b>Blocklisted:</b> {', '.join(sorted(tag_blocklist))}</p>"
    tag_html += "<h3 style='margin:12px 0;'>Canary outcomes</h3><table><tr><th>Asset</th><th>Result</th><th>Reason</th></tr>"
    if canary_outcomes:
        for oc in canary_outcomes:
            cls = "ok" if oc.get("result")=="PASS" else "bad"
            tag_html += f"<tr><td>{oc.get('asset')}</td><td class='{cls}'>{oc.get('result')}</td><td>{oc.get('reason','—')}</td></tr>"
    else:
        tag_html += "<tr><td colspan='3' class='small'>No canary events recorded today.</td></tr>"
    tag_html += "</table></div>"

    venue_html = "<div class='grid section'>"
    venue_html += "<div><h2>Venue profile changes (24h)</h2><table><tr><th>Asset::Venue</th><th>Mode</th><th>Slices</th><th>Delay ms</th><th>Vol band</th></tr>"
    for row in venue_rows:
        venue_html += f"<tr><td>{row['key']}</td><td>{row['mode']}</td><td>{row['slice']}</td><td>{row['delay']}</td><td>{row['vol_band']}</td></tr>"
    if not venue_rows:
        venue_html += "<tr><td colspan='5' class='small'>No venue updates recorded.</td></tr>"
    venue_html += "</table></div>"

    overrides_html = "<div><h2>Applied intraday overrides</h2><table><tr><th>Asset</th><th>Scale</th><th>Router</th><th>Hold</th><th>Swap</th></tr>"
    for row in sorted(overrides_rows, key=lambda x: x["asset"]):
        overrides_html += f"<tr><td>{row['asset']}</td><td>{row['scale']}</td><td>{row['router']}</td><td>{row['hold_orders']}</td><td>{row['swap']}</td></tr>"
    if not overrides_rows:
        overrides_html += "<tr><td colspan='5' class='small'>No overrides applied.</td></tr>"
    overrides_html += "</table></div></div>"

    html = f"<!doctype html><html><head>{styles}</head><body><div class='wrap'>{header}{pnl_pill}{wl_html}{chart_html}{learned}{tag_html}{venue_html}{overrides_html}</div></body></html>"
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

def send_nightly_email_report_v2():
    subject = f"[Nightly] Autonomous Crypto Desk — Executive Report ({_ts()})"
    html = build_email_html()
    send_email_html(subject, html)
    print("Nightly executive email sent.")

if __name__ == "__main__":
    html = build_email_html()
    print(html[:1200] + "\n...\n")
    if os.environ.get("SEND","0") == "1":
        send_nightly_email_report_v2()
