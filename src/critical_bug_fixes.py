# src/critical_bug_fixes.py
#
# Critical Bug Fixes + Diagnostic Audit
# - Fix margin accounting corruption
# - Fix trade recording data loss
# - Fix stale metrics handling
# - Nightly diagnostic audit to verify integrity

import os, json, time

LOG_DIR = "logs"
TRADE_LOG = os.path.join(LOG_DIR,"trade_log.jsonl")
METRIC_LOG = os.path.join(LOG_DIR,"metrics.jsonl")
AUDIT_LOG = os.path.join(LOG_DIR,"diagnostic_audit.jsonl")

def _now(): return int(time.time())
def _append_jsonl(path,obj): os.makedirs(os.path.dirname(path),exist_ok=True); open(path,"a").write(json.dumps(obj)+"\n")
def _read_jsonl(path): return [json.loads(l) for l in open(path)] if os.path.exists(path) else []

# ======================================================================
# 1. Margin Accounting Fix
# ======================================================================
def calculate_available_margin(balance, reserved, positions):
    """
    Ensure available margin = balance - reserved - open_position_margin
    Prevents inflated margin accounting.
    """
    used_margin = sum(p.get('margin',0.0) for p in positions)
    available = balance - reserved - used_margin
    # Sanity check: never exceed balance
    if available > balance:
        available = balance - reserved
    return max(0, round(available,2))

# ======================================================================
# 2. Trade Recording Fix
# ======================================================================
def calculate_fees(size, price, fee_rate=0.001):
    return round(size*price*fee_rate,4)

def record_trade(trade):
    """
    Ensure every trade record includes ROI, fees, and close_reason.
    """
    entry_price = trade.get('entry_price')
    exit_price = trade.get('exit_price')
    size = trade.get('size',0.0)

    if entry_price and exit_price:
        trade['roi'] = round((exit_price-entry_price)/entry_price,4)
    else:
        trade['roi'] = None

    trade['fees'] = calculate_fees(size, entry_price or 0.0)
    trade['close_reason'] = trade.get('close_reason','system_exit')

    _append_jsonl(TRADE_LOG,trade)
    return trade

# ======================================================================
# 3. Stale Metrics Fix
# ======================================================================
def validate_metric(metric, max_age_hours=24):
    """
    Reject metrics older than max_age_hours.
    """
    age_hours = (time.time()-metric['ts'])/3600
    if age_hours > max_age_hours:
        return {"valid":False,"reason":"stale"}
    return {"valid":True,"value":metric['value']}

# ======================================================================
# 4. Diagnostic Audit
# ======================================================================
def run_diagnostic_audit(balance, reserved, positions):
    """
    Nightly audit: margin integrity, trade completeness, metric freshness.
    """
    # Margin check
    available = calculate_available_margin(balance,reserved,positions)
    margin_ok = available <= balance and available >= 0

    # Trade completeness check
    trades = _read_jsonl(TRADE_LOG)
    incomplete_trades = [t for t in trades if t.get('roi') in (None,0) or t.get('fees')==0 or t.get('close_reason')=="unknown"]

    # Metric freshness check
    metrics = _read_jsonl(METRIC_LOG)
    stale_metrics = [m for m in metrics if not validate_metric(m)["valid"]]

    audit = {
        "ts":_now(),
        "margin_ok":margin_ok,
        "available_margin":available,
        "incomplete_trades":len(incomplete_trades),
        "stale_metrics":len(stale_metrics)
    }
    _append_jsonl(AUDIT_LOG,audit)
    return audit

# CLI quick run
if __name__=="__main__":
    # Example usage
    balance,reserved,positions = 10000.0, 1000.0,[{"margin":500.0}]
    trade = {"entry_price":20000,"exit_price":21000,"size":0.1}
    record_trade(trade)
    metric = {"ts":time.time()-25*3600,"value":123}
    _append_jsonl(METRIC_LOG,metric)

    audit = run_diagnostic_audit(balance,reserved,positions)
    print("Diagnostic Audit Summary:",json.dumps(audit,indent=2))
