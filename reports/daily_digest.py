import json
import gzip
import datetime as dt
from pathlib import Path
from dateutil import parser as dtparser
from collections import defaultdict

LOG_DIR = Path("/root/trading-bot/logs")
DIGEST_DIR = Path("/root/trading-bot/reports")
DIGEST_DIR.mkdir(parents=True, exist_ok=True)

RETENTION_DAYS = 30

def parse_ts(ts_str):
    try:
        ts = dtparser.isoparse(ts_str)
        # If timestamp is naive, assume local timezone
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=dt.datetime.now().astimezone().tzinfo)
        return ts
    except Exception:
        return None

def load_jsonl(path):
    items = []
    if not path.exists():
        return items
    try:
        with path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        pass
    return items

def load_json(path):
    if not path.exists():
        return None
    try:
        with path.open() as f:
            return json.load(f)
    except Exception:
        return None

def load_json_gz(path):
    items = []
    if not path.exists():
        return items
    try:
        with gzip.open(path, "rt") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        pass
    return items

def within_last_24h(ts, now):
    if ts is None:
        return False
    return (now - ts).total_seconds() <= 24 * 3600

def load_trades():
    path = LOG_DIR / "executed_trades.jsonl"
    return load_jsonl(path)

def load_signals():
    path = LOG_DIR / "signals.jsonl"
    return load_jsonl(path)

def load_missed_opportunities():
    path = LOG_DIR / "missed_opportunities.json"
    data = load_json(path)
    if not data or "missed_trades" not in data:
        return []
    return data["missed_trades"]

def load_performance():
    path = LOG_DIR / "performance.json"
    data = load_json(path)
    if isinstance(data, list):
        return data
    return []

def filter_last_24h(items, now, ts_field="timestamp"):
    out = []
    for item in items:
        ts_raw = item.get(ts_field)
        ts = parse_ts(ts_raw)
        if within_last_24h(ts, now):
            out.append(item)
    return out

# ============================
# 24-HOUR INTEGRITY HELPERS
# ============================

def load_meta_learning_last_24h(now):
    path = LOG_DIR / "meta_learning.jsonl"
    items = load_jsonl(path)
    return filter_last_24h(items, now, ts_field="ts")


def load_learning_updates_last_24h(now):
    path = LOG_DIR / "learning_updates.jsonl"
    items = load_jsonl(path)
    return filter_last_24h(items, now, ts_field="ts")


def summarize_orchestrator_health(now):
    recent = load_meta_learning_last_24h(now)

    if not recent:
        return [
            "Orchestrator: ⚠️ No meta-learning entries in last 24 hours (check cadence / orchestrator scheduling)."
        ]

    total = len(recent)
    quarantines = sum(
        1 for r in recent
        if r.get("update_type") == "preflight_fail_quarantine"
    )
    normal_cycles = sum(
        1 for r in recent
        if r.get("update_type") not in ("preflight_fail_quarantine", None)
    )

    last = recent[-1]
    last_type = last.get("update_type", "unknown")

    lines = []
    if quarantines == 0:
        lines.append("Orchestrator: ✅ Healthy (no quarantine events in last 24h).")
    else:
        lines.append(
            f"Orchestrator: ⚠️ {quarantines} quarantine event(s) in last 24h."
        )

    lines.append(f"- Meta-learning events (24h): {total}")
    lines.append(f"- Non-quarantine events (24h): {normal_cycles}")
    lines.append(f"- Last event type: {last_type}")

    return lines


def summarize_learning_activity(now):
    recent = load_learning_updates_last_24h(now)

    if not recent:
        return ["Learning Activity: ⚠️ No learning updates in last 24h."]

    total = len(recent)
    signal_adjustments = sum(
        1 for r in recent
        if r.get("update_type") == "signal_adjustment_propagated"
    )
    recovery_cycles = sum(
        1 for r in recent
        if r.get("update_type") == "recovery_cycle"
    )
    fee_audits = sum(
        1 for r in recent
        if r.get("update_type") == "fee_venue_audit"
    )

    lines = []
    lines.append("Learning Activity: 📘")
    lines.append(f"- Total updates (24h): {total}")
    lines.append(f"- Signal adjustments: {signal_adjustments}")
    lines.append(f"- Recovery cycles: {recovery_cycles}")
    lines.append(f"- Fee audits: {fee_audits}")

    return lines


def summarize_system_heartbeat():
    lines = []

    # Process heartbeat
    proc_path = LOG_DIR / "process_heartbeat.json"
    proc_info = {}
    try:
        if proc_path.exists():
            with proc_path.open("r") as f:
                last_line = None
                for line in f:
                    if line.strip():
                        last_line = line
                if last_line:
                    proc_info = json.loads(last_line)
    except Exception:
        proc_info = {}

    if proc_info:
        pid = proc_info.get("pid")
        ts_str = proc_info.get("timestamp")
        uptime = proc_info.get("uptime_seconds")
        mem_mb = proc_info.get("memory_mb")

        try:
            uptime_str = f"{uptime:.0f}s" if uptime is not None else "unknown"
        except TypeError:
            uptime_str = "unknown"

        lines.append(
            f"System Heartbeat: 💓 Process alive (pid={pid}, ts={ts_str}, uptime={uptime_str}, mem={mem_mb} MB)"
        )
    else:
        lines.append("System Heartbeat: ❌ No process heartbeat info available.")

    # Supervisor heartbeat
    sup_path = LOG_DIR / "supervisor_heartbeat.txt"
    sup_ts = None
    try:
        if sup_path.exists():
            with sup_path.open("r") as f:
                last_line = None
                for line in f:
                    if line.strip():
                        last_line = line.strip()
                sup_ts = last_line
    except Exception:
        sup_ts = None

    if sup_ts:
        lines.append(f"- Supervisor heartbeat: {sup_ts}")
    else:
        lines.append("- Supervisor heartbeat: missing.")

    return lines

def compute_trade_metrics(trades):
    total_trades = len(trades)
    wins = 0
    losses = 0
    pnl_sum = 0.0
    fee_sum = 0.0
    pnl_list = []

    strategy_perf = defaultdict(lambda: {"pnl": 0.0, "count": 0})
    symbol_perf = defaultdict(lambda: {"pnl": 0.0, "count": 0})

    for t in trades:
        pnl = t.get("net_pnl", 0.0)
        pnl_sum += pnl
        pnl_list.append(pnl)

        fees = t.get("fees", 0.0)
        fee_sum += fees

        if pnl > 0:
            wins += 1
        elif pnl < 0:
            losses += 1

        strat = t.get("strategy_id", "unknown")
        strategy_perf[strat]["pnl"] += pnl
        strategy_perf[strat]["count"] += 1

        sym = t.get("symbol", "unknown")
        symbol_perf[sym]["pnl"] += pnl
        symbol_perf[sym]["count"] += 1

    win_rate = (wins / total_trades) * 100 if total_trades > 0 else 0.0
    max_drawdown = min(pnl_list) if pnl_list else 0.0

    return {
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "net_pnl": pnl_sum,
        "fees": fee_sum,
        "max_drawdown": max_drawdown,
        "strategy_perf": strategy_perf,
        "symbol_perf": symbol_perf,
    }

def compute_missed_metrics(missed):
    total = len(missed)
    roi_sum = 0.0
    by_symbol = defaultdict(lambda: {"count": 0, "roi": 0.0})
    by_reason = defaultdict(int)

    for m in missed:
        roi = m.get("missed_roi", 0.0)
        roi_sum += roi

        sym = m.get("symbol", "unknown")
        by_symbol[sym]["count"] += 1
        by_symbol[sym]["roi"] += roi

        reasons = m.get("filters_blocked", [])
        if isinstance(reasons, list):
            for r in reasons:
                by_reason[r] += 1

    avg_roi = roi_sum / total if total > 0 else 0.0

    return {
        "total_missed": total,
        "avg_missed_roi": avg_roi,
        "symbol_missed": by_symbol,
        "reason_counts": by_reason,
    }

def compute_blocked_signal_metrics(signals):
    total = len(signals)
    by_symbol = defaultdict(int)
    by_reason = defaultdict(int)

    for s in signals:
        sym = s.get("symbol", "unknown")
        by_symbol[sym] += 1

        reason = s.get("block_reason", "unknown")
        by_reason[reason] += 1

    return {
        "total_blocked": total,
        "by_symbol": by_symbol,
        "by_reason": by_reason,
    }


def compute_performance_metrics(perf_entries, now):
    last_24 = []
    for p in perf_entries:
        ts = parse_ts(p.get("timestamp"))
        if ts and (now - ts).total_seconds() <= 24 * 3600:
            last_24.append(p)

    if not last_24:
        return {
            "portfolio_change": 0.0,
            "max_drawdown": 0.0,
            "start_value": None,
            "end_value": None,
        }

    start_value = last_24[0].get("portfolio_value")
    end_value = last_24[-1].get("portfolio_value")
    change = (end_value - start_value) if (start_value is not None and end_value is not None) else 0.0

    max_dd = min([p.get("max_drawdown", 0.0) for p in last_24])

    return {
        "portfolio_change": change,
        "max_drawdown": max_dd,
        "start_value": start_value,
        "end_value": end_value,
    }

def load_past_digests():
    digests = []
    for path in sorted(DIGEST_DIR.glob("digest_*.json")):
        try:
            with path.open() as f:
                digests.append(json.load(f))
        except Exception:
            continue
    return digests


def keep_recent_digests():
    digests = sorted(DIGEST_DIR.glob("digest_*.json"))
    if len(digests) <= RETENTION_DAYS:
        return
    to_delete = digests[:-RETENTION_DAYS]
    for p in to_delete:
        try:
            p.unlink()
        except Exception:
            pass


def get_last_n_digests(n):
    digests = load_past_digests()
    if len(digests) < n:
        return digests
    return digests[-n:]


def compute_rolling_2day(today_digest, past_digests):
    if not past_digests:
        return None

    yesterday = past_digests[-1]
    return {
        "pnl_change": today_digest["net_pnl"] - yesterday.get("net_pnl", 0.0),
        "win_rate_change": today_digest["win_rate"] - yesterday.get("win_rate", 0.0),
        "missed_change": today_digest["missed_total"] - yesterday.get("missed_total", 0),
        "blocked_change": today_digest["blocked_total"] - yesterday.get("blocked_total", 0),
        "evolution_change": today_digest["evolution_score"] - yesterday.get("evolution_score", 0.0),
    }


def compute_rolling_7day(past_digests):
    if not past_digests:
        return None

    pnl_sum = sum(d.get("net_pnl", 0.0) for d in past_digests)
    trades_sum = sum(d.get("total_trades", 0) for d in past_digests)
    missed_sum = sum(d.get("missed_total", 0) for d in past_digests)
    blocked_sum = sum(d.get("blocked_total", 0) for d in past_digests)
    evo_scores = [d.get("evolution_score", 0.0) for d in past_digests]

    return {
        "pnl_7d": pnl_sum,
        "avg_daily_pnl": pnl_sum / len(past_digests),
        "total_trades_7d": trades_sum,
        "missed_7d": missed_sum,
        "blocked_7d": blocked_sum,
        "evolution_avg": sum(evo_scores) / len(evo_scores),
    }

def compute_evolution_score(trade_metrics, missed_metrics, blocked_metrics, perf_metrics):
    score = 50.0

    # Profitability
    pnl = trade_metrics.get("net_pnl", 0.0)
    if pnl > 0:
        score += min(20, pnl * 2)
    else:
        score += max(-20, pnl * 2)

    # Win rate
    win_rate = trade_metrics.get("win_rate", 0.0)
    score += (win_rate - 50) * 0.2

    # Missed opportunities
    missed = missed_metrics.get("total_missed", 0)
    score -= min(10, missed * 0.5)

    # Blocked signals
    blocked = blocked_metrics.get("total_blocked", 0)
    score -= min(10, blocked * 0.2)

    # Drawdown
    dd = perf_metrics.get("max_drawdown", 0.0)
    score -= min(10, abs(dd) * 100)

    return max(0, min(100, score))


def build_markdown_report(
    now,
    trade_metrics,
    missed_metrics,
    blocked_metrics,
    perf_metrics,
    evo_score,
    rolling_2d,
    rolling_7d
):
    md = []
    md.append(f"# Daily Digest — {now.isoformat()}")
    md.append("")
    # ================================
    # ✅ 24-Hour System Integrity Check
    # ================================
    md.append("## ✅ 24-Hour System Integrity Check")
    for line in summarize_orchestrator_health(now):
        md.append(line)
    for line in summarize_learning_activity(now):
        md.append(line)
    for line in summarize_system_heartbeat():
        md.append(line)
    md.append("")
    md.append("## ✅ Last 24 Hours Performance")
    md.append(f"- **Net PnL:** {trade_metrics['net_pnl']:.4f}")
    md.append(f"- **Win Rate:** {trade_metrics['win_rate']:.2f}%")
    md.append(f"- **Total Trades:** {trade_metrics['total_trades']}")
    md.append(f"- **Fees Paid:** {trade_metrics['fees']:.4f}")
    md.append(f"- **Max Drawdown:** {trade_metrics['max_drawdown']:.4f}")
    md.append("")

    md.append("## ✅ Missed Opportunities")
    md.append(f"- **Total Missed:** {missed_metrics['total_missed']}")
    md.append(f"- **Avg Missed ROI:** {missed_metrics['avg_missed_roi']:.4f}")
    md.append("")

    md.append("## ✅ Blocked Signals")
    md.append(f"- **Total Blocked:** {blocked_metrics['total_blocked']}")
    md.append("")

    md.append("## ✅ Portfolio Movement")
    md.append(f"- **Start Value:** {perf_metrics['start_value']}")
    md.append(f"- **End Value:** {perf_metrics['end_value']}")
    md.append(f"- **Change:** {perf_metrics['portfolio_change']:.4f}")
    md.append("")

    md.append(f"## ✅ Evolution Score: **{evo_score:.2f} / 100**")
    md.append("")

    if rolling_2d:
        md.append("## 🔄 Rolling 2‑Day Comparison")
        md.append(f"- PnL Change: {rolling_2d['pnl_change']:.4f}")
        md.append(f"- Win Rate Change: {rolling_2d['win_rate_change']:.2f}")
        md.append(f"- Missed Change: {rolling_2d['missed_change']}")
        md.append(f"- Blocked Change: {rolling_2d['blocked_change']}")
        md.append(f"- Evolution Change: {rolling_2d['evolution_change']:.2f}")
        md.append("")

    if rolling_7d:
        md.append("## 📅 Rolling 7‑Day Summary")
        md.append(f"- Total PnL (7d): {rolling_7d['pnl_7d']:.4f}")
        md.append(f"- Avg Daily PnL: {rolling_7d['avg_daily_pnl']:.4f}")
        md.append(f"- Total Trades (7d): {rolling_7d['total_trades_7d']}")
        md.append(f"- Missed (7d): {rolling_7d['missed_7d']}")
        md.append(f"- Blocked (7d): {rolling_7d['blocked_7d']}")
        md.append(f"- Avg Evolution Score: {rolling_7d['evolution_avg']:.2f}")
        md.append("")

    return "\n".join(md)

def build_daily_digest():
    now = dt.datetime.now(dt.timezone.utc).astimezone()  # keep local offset

    # Load logs
    trades = load_trades()
    signals = load_signals()
    missed = load_missed_opportunities()
    perf = load_performance()

    # Filter last 24 hours
    trades_24h = filter_last_24h(trades, now)
    signals_24h = filter_last_24h(signals, now, ts_field="ts_iso")
    missed_24h = filter_last_24h(missed, now, ts_field="timestamp")

    # Compute metrics
    trade_metrics = compute_trade_metrics(trades_24h)
    missed_metrics = compute_missed_metrics(missed_24h)
    blocked_metrics = compute_blocked_signal_metrics(signals_24h)
    perf_metrics = compute_performance_metrics(perf, now)

    # Evolution score
    evo_score = compute_evolution_score(
        trade_metrics,
        missed_metrics,
        blocked_metrics,
        perf_metrics
    )

    # Rolling windows
    past_digests = load_past_digests()
    rolling_2d = compute_rolling_2day(
        {
            "net_pnl": trade_metrics["net_pnl"],
            "win_rate": trade_metrics["win_rate"],
            "missed_total": missed_metrics["total_missed"],
            "blocked_total": blocked_metrics["total_blocked"],
            "evolution_score": evo_score,
            "total_trades": trade_metrics["total_trades"],
        },
        past_digests
    )

    last_7 = get_last_n_digests(7)
    rolling_7d = compute_rolling_7day(last_7)

    # Build markdown
    md = build_markdown_report(
        now,
        trade_metrics,
        missed_metrics,
        blocked_metrics,
        perf_metrics,
        evo_score,
        rolling_2d,
        rolling_7d
    )

    # Save markdown
    md_path = DIGEST_DIR / "digest_latest.md"
    with md_path.open("w") as f:
        f.write(md)

    # Save JSON digest for future rolling windows
    digest_json = {
        "timestamp": now.isoformat(),
        "net_pnl": trade_metrics["net_pnl"],
        "win_rate": trade_metrics["win_rate"],
        "total_trades": trade_metrics["total_trades"],
        "missed_total": missed_metrics["total_missed"],
        "blocked_total": blocked_metrics["total_blocked"],
        "evolution_score": evo_score,
    }

    json_path = DIGEST_DIR / f"digest_{now.strftime('%Y%m%d_%H%M%S')}.json"
    with json_path.open("w") as f:
        json.dump(digest_json, f, indent=2)

    # Retention cleanup
    keep_recent_digests()

    # Print to terminal
    print(md)

if __name__ == "__main__":
    build_daily_digest()

