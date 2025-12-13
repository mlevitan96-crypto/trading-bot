# src/profit_blofin_learning.py

import os, json, time
from collections import defaultdict

EVENTS_LOG = "logs/unified_events.jsonl"
POS_LOG    = "logs/positions_futures.json"
POLICY_CFG = "config/profit_policy.json"

# --- Global defaults & bounds ---
DEFAULTS = {"MIN_PROFIT_USD": 2.0, "BASE_COLLATERAL_USD": 500.0, "INTERNAL_MAX_LEVERAGE": 10}
BOUNDS   = {"MIN_PROFIT_USD": (1.0,50.0), "BASE_COLLATERAL_USD": (250.0,5000.0), "INTERNAL_MAX_LEVERAGE": (3,20)}

# --- Blofin venue caps ---
BLOFIN_MAX_LEVERAGE_BY_CONTRACT = {"BTCUSDT":150,"ETHUSDT":100,"SOLUSDT":75,"AVAXUSDT":50,"DOTUSDT":50,"TRXUSDT":50}
DEFAULT_MARGIN_MODE = "isolated"
ALLOWED_MARGIN_MODES = {"isolated","cross"}
MAX_EXPOSURE_MULT = 3.0

# --- Shadow symbols ---
SHADOW_SYMBOLS = ["XRPUSDT","ADAUSDT","DOGEUSDT","BNBUSDT","MATICUSDT"]

# --- Runtime feature flag check (evaluates on each call) ---
def is_profit_learning_enabled() -> bool:
    """Check if profit learning is enabled via environment variable (runtime check)."""
    return bool(os.getenv("ENABLE_PROFIT_LEARNING", "1") == "1")

# --- Kill-switch stabilization config ---
KILL_SWITCH_CFG = {
    "max_drawdown_pct": 15.0,
    "fee_mismatch_usd": 50.0,
    "reject_rate_pct": 25.0,
    "freeze_duration_min": 15,
}

# --- Budget caps fix ---
DEFAULT_MIN_COLLATERAL_USD = 500.0
SYMBOL_BUDGET_USD = defaultdict(lambda: DEFAULT_MIN_COLLATERAL_USD)

def get_symbol_budget(symbol: str) -> float:
    """Ensure symbol budget never hits $0. Always return minimum $500."""
    budget = SYMBOL_BUDGET_USD.get(symbol, DEFAULT_MIN_COLLATERAL_USD)
    if budget <= 0:
        log_event("budget_zero_fix", {"symbol": symbol, "old_budget": budget, "new_budget": DEFAULT_MIN_COLLATERAL_USD})
        budget = DEFAULT_MIN_COLLATERAL_USD
        SYMBOL_BUDGET_USD[symbol] = budget
    return max(budget, DEFAULT_MIN_COLLATERAL_USD)

# --- IO helpers ---
def _read_jsonl(path):
    if not os.path.exists(path): return []
    out=[]
    with open(path,"r") as f:
        for line in f:
            try: out.append(json.loads(line))
            except: continue
    return out

def _append_json(path,obj):
    os.makedirs(os.path.dirname(path),exist_ok=True)
    with open(path,"a") as f: f.write(json.dumps(obj)+"\n")

def _read_policy():
    if not os.path.exists(POLICY_CFG):
        return {"global": DEFAULTS.copy(),"per_symbol":{}}
    try:
        with open(POLICY_CFG,"r") as f: return json.load(f)
    except: return {"global": DEFAULTS.copy(),"per_symbol":{}}

def _write_policy(cfg):
    os.makedirs(os.path.dirname(POLICY_CFG),exist_ok=True)
    with open(POLICY_CFG,"w") as f: json.dump(cfg,f,indent=2)

def log_event(event: str, payload: dict = None):
    """Centralized event logging."""
    payload = dict(payload or {})
    payload.update({"ts": int(time.time()), "event": event})
    _append_json(EVENTS_LOG, payload)

def freeze_entries(minutes: int = 15):
    """Freeze new entries globally for specified minutes."""
    log_event("entries_frozen", {"minutes": minutes})
    print(f"🚨 [PROFIT-LEARN] Entries frozen for {minutes} minutes")

def request_performance_rebaseline():
    """Request performance metrics rebaseline."""
    log_event("performance_rebaseline_requested", {})
    print("📊 [PROFIT-LEARN] Performance rebaseline requested")

def evaluate_kill_switch(metrics: dict) -> bool:
    """
    Evaluate kill-switch criteria with corruption detection.
    Fixes false triggers from corrupted DD values (e.g., 310%).
    Includes minimum-trade safeguard (<10 fills bypass) and age gate (>6h old metrics ignored).
    """
    dd = float(metrics.get("drawdown_pct", 0.0))
    rej = float(metrics.get("reject_rate_pct", 0.0))
    fee = float(metrics.get("fee_mismatch_usd", 0.0))
    
    sample_count = int(metrics.get("total_fills", 0))
    age_hours = float(metrics.get("age_hours", 0.0))
    
    if sample_count < 10:
        log_event("kill_switch_bypass_low_samples", {"sample_count": sample_count})
        print(f"✅ [PROFIT-LEARN] Kill-switch bypassed: Low sample count ({sample_count} fills < 10)")
        return False
    
    if age_hours > 6.0:
        # CRITICAL FIX: Validate that bypassing with stale metrics is safe
        from src.critical_bug_fixes import validate_metric
        metric_validation = validate_metric({"ts": time.time() - age_hours*3600, "value": dd}, max_age_hours=24)
        
        if age_hours > 24.0:
            # Metrics >24h are too old - don't bypass, use emergency mode
            log_event("kill_switch_emergency_stale", {"age_hours": age_hours})
            print(f"⚠️ [PROFIT-LEARN] Emergency: Metrics critically stale ({age_hours:.1f}h > 24h) - Trading RESTRICTED")
            return True  # Keep freeze active for safety
        else:
            # Metrics 6-24h old - cautious bypass with logging
            log_event("kill_switch_bypass_stale_metrics", {"age_hours": age_hours})
            print(f"⚠️ [PROFIT-LEARN] Caution: Stale metrics ({age_hours:.1f}h) → Trading allowed (refresh metrics soon)")
            return False

    # Critical fix: Detect corrupted drawdown metrics
    if dd > 100.0:
        log_event("kill_switch_metrics_corrupt", {"dd": dd, "original_value": dd})
        print(f"⚠️  [PROFIT-LEARN] Corrupted DD detected: {dd}% → Reset to 0%")
        dd = 0.0

    triggered = (
        dd >= KILL_SWITCH_CFG["max_drawdown_pct"] or
        rej >= KILL_SWITCH_CFG["reject_rate_pct"] or
        fee >= KILL_SWITCH_CFG["fee_mismatch_usd"]
    )

    if triggered:
        log_event("kill_switch_triggered", {"dd": dd, "rej": rej, "fee": fee})
        freeze_entries(minutes=KILL_SWITCH_CFG["freeze_duration_min"])
        request_performance_rebaseline()
        print(f"🚨 [PROFIT-LEARN] Kill-switch triggered: DD={dd}%, Reject={rej}%, Fee=${fee}")
    
    return triggered

# --- Profit filter & leverage logic ---
def expected_profit_usd(signal:dict) -> float:
    roi = float(signal.get("roi",0.0))
    size_usd = float(signal.get("size_usd") or planned_position_size_usd(signal) or 0.0)
    return roi * size_usd

def profit_filter(signal:dict, sym_cfg:dict) -> bool:
    exp_profit = expected_profit_usd(signal)
    if exp_profit < sym_cfg["MIN_PROFIT_USD"]:
        _append_json(EVENTS_LOG,{"ts":int(time.time()),"event":"profit_filter_block","symbol":signal.get("symbol"),"expected_profit":exp_profit})
        return False
    return True

def venue_max_leverage(symbol:str) -> int:
    return BLOFIN_MAX_LEVERAGE_BY_CONTRACT.get(symbol,20)

def choose_margin_mode(signal:dict) -> str:
    mode = str(signal.get("margin_mode",DEFAULT_MARGIN_MODE)).lower()
    return mode if mode in ALLOWED_MARGIN_MODES else DEFAULT_MARGIN_MODE

def confidence_scaled_leverage(signal:dict, rolling_expectancy:float, sym_cfg:dict) -> int:
    roi = float(signal.get("roi",0.0))
    conf = int(signal.get("confirmations",0))
    lev = 1
    if roi>=0.005 and conf>=2 and rolling_expectancy>0:
        if roi>=0.01: lev=10
        elif roi>=0.0075: lev=6
        elif roi>=0.005: lev=3
    return min(lev, sym_cfg["INTERNAL_MAX_LEVERAGE"])

def risk_clamp_leverage(symbol:str, desired:int, wallet_balance:float, size_usd:float, sym_cfg:dict) -> int:
    venue_cap = venue_max_leverage(symbol)
    internal_cap = sym_cfg["INTERNAL_MAX_LEVERAGE"]
    if wallet_balance>0 and size_usd>0:
        max_notional = wallet_balance*MAX_EXPOSURE_MULT
        exposure_bound = int(max(1,min(venue_cap,max_notional//size_usd)))
    else: exposure_bound=1
    return int(max(1,min(desired,venue_cap,internal_cap,exposure_bound)))

# --- Stub implementations (integrate with existing bot) ---
def planned_position_size_usd(signal:dict) -> float:
    """Extract planned position size from signal or use default."""
    return float(signal.get("position_size_usd", 500.0))

def get_current_price(symbol:str) -> float:
    """Get current market price for symbol."""
    try:
        from src.exchange_gateway import ExchangeGateway
        gw = ExchangeGateway()
        price = gw.get_futures_mark_price(symbol)
        return float(price) if price else 0.0
    except:
        return 0.0

def compute_stop_loss(entry_price:float, wallet_balance:float, side:str) -> float:
    """Compute stop loss price with 2% wallet risk cap."""
    risk_pct = 0.02
    if side.lower() in ("buy","long"):
        return entry_price * (1 - risk_pct)
    else:
        return entry_price * (1 + risk_pct)


def _aggregate_performance():
    """Aggregate per-symbol performance stats."""
    events = _read_jsonl(EVENTS_LOG)
    stats = defaultdict(lambda: {"trades":0,"wins":0,"total_pnl":0.0,"total_profit":0.0})
    
    for evt in events:
        if evt.get("event") == "profit_blofin_entry":
            sym = evt.get("symbol","")
            exp_profit = evt.get("expected_profit_usd",0.0)
            stats[sym]["trades"] += 1
            stats[sym]["total_profit"] += exp_profit
    
    return dict(stats)

def _adjust_symbol_policy(stats:dict, current:dict):
    """Adjust policy based on performance stats."""
    updated = current.copy()
    
    # If high win rate and good profits, slightly increase leverage cap
    if stats.get("trades",0) >= 10:
        win_rate = stats.get("wins",0) / stats["trades"]
        avg_profit = stats.get("total_profit",0.0) / stats["trades"]
        
        if win_rate >= 0.6 and avg_profit > current["MIN_PROFIT_USD"]:
            updated["INTERNAL_MAX_LEVERAGE"] = min(
                current["INTERNAL_MAX_LEVERAGE"] + 1,
                BOUNDS["INTERNAL_MAX_LEVERAGE"][1]
            )
        elif win_rate < 0.4:
            updated["INTERNAL_MAX_LEVERAGE"] = max(
                current["INTERNAL_MAX_LEVERAGE"] - 1,
                BOUNDS["INTERNAL_MAX_LEVERAGE"][0]
            )
    
    return updated

# --- Shadow promotion ---
def promote_shadow_symbols():
    """Initialize shadow symbols in policy config with shadow_tag."""
    policy=_read_policy()
    for sym in SHADOW_SYMBOLS:
        if sym not in policy["per_symbol"]:
            policy["per_symbol"][sym]=policy["global"].copy()
            policy["per_symbol"][sym]["shadow_tag"]=True
    _write_policy(policy)

# --- Entry wrapper ---
def open_profit_blofin_entry(signal:dict, wallet_balance:float, rolling_expectancy:float):
    """
    Apply profit-first gating and return enriched trading parameters.
    Does NOT place orders - returns parameters for caller to execute via existing pipeline.
    
    Returns:
        {
            "status": "approved" | "blocked",
            "reason": str (if blocked),
            "params": {  # If approved
                "symbol": str,
                "side": str,
                "strategy": str,
                "leverage": int,
                "margin_usd": float,
                "entry_price": float,
                "stop_loss": float,
                "margin_mode": str,
                "expected_profit_usd": float,
                "shadow_tag": bool
            }
        }
    """
    policy=_read_policy()
    sym_cfg=policy["per_symbol"].get(signal.get("symbol",""),policy["global"])

    symbol=signal.get("symbol","")
    side=signal.get("side","").lower()
    strategy=signal.get("strategy","EMA-Futures")
    
    if not symbol or side not in("buy","long","sell","short"):
        log_event("entry_block_invalid_signal",{"signal":signal})
        return {"status":"blocked","reason":"invalid_signal"}

    if not profit_filter(signal,sym_cfg):
        return {"status":"blocked","reason":"profit_filter"}

    margin_usd=float(signal.get("size_usd") or planned_position_size_usd(signal) or 0.0)
    if margin_usd<sym_cfg["BASE_COLLATERAL_USD"]:
        margin_usd=sym_cfg["BASE_COLLATERAL_USD"]

    entry_price=float(signal.get("entry_price") or get_current_price(symbol) or 0.0)
    stop_price=compute_stop_loss(entry_price,wallet_balance,side)

    desired=confidence_scaled_leverage(signal,rolling_expectancy,sym_cfg)
    leverage=risk_clamp_leverage(symbol,desired,float(wallet_balance or 0.0),margin_usd,sym_cfg)
    margin_mode=choose_margin_mode(signal)

    params={
        "symbol":symbol,"side":side,"strategy":strategy,"leverage":leverage,
        "margin_usd":margin_usd,"entry_price":entry_price,"stop_loss":stop_price,
        "margin_mode":margin_mode,"expected_profit_usd":expected_profit_usd(signal),
        "shadow_tag":symbol in SHADOW_SYMBOLS,"venue_cap":venue_max_leverage(symbol)
    }

    evt={"ts":int(time.time()),"event":"profit_blofin_approved",**params}
    log_event("profit_blofin_approved",params)
    
    return {"status":"approved","params":params}

# --- Learning adjustment ---
def adjust_profit_policy():
    cfg=_read_policy()
    stats=_aggregate_performance()
    if "global" not in cfg: cfg["global"]=DEFAULTS.copy()
    if "per_symbol" not in cfg: cfg["per_symbol"]={}

    for sym,s in stats.items():
        current=cfg["per_symbol"].get(sym,cfg["global"])
        updated=_adjust_symbol_policy(s,current)
        cfg["per_symbol"][sym]=updated
        _append_json(EVENTS_LOG,{"ts":int(time.time()),"event":"profit_policy_update","symbol":sym,"from":current,"to":updated,"stats":s})

    _write_policy(cfg)
    print("[PROFIT-LEARN] Policy adjusted and saved.")

# --- Periodic scheduling ---
def schedule_profit_learning(register_periodic_task):
    def tick():
        try: adjust_profit_policy()
        except Exception as e:
            _append_json(EVENTS_LOG,{"ts":int(time.time()),"event":"profit_policy_error","err":str(e)})
    register_periodic_task(tick,interval_sec=15*60)

# --- Dashboard integration ---
def make_trade_history_table(df):
    """Create Dash DataTable for trade history with shadow symbol highlighting."""
    try:
        import dash_table
        import dash_core_components as dcc
        import dash_html_components as html
        import dash_bootstrap_components as dbc
    except ImportError:
        return None
    
    cols=[
        {"name":"Symbol","id":"symbol"},
        {"name":"Side","id":"side"},
        {"name":"Cost (USD)","id":"cost_usd","type":"numeric","format":{"specifier":".2f"}},
        {"name":"Coins","id":"coins","type":"numeric","format":{"specifier":".6f"}},
        {"name":"Entry Price","id":"entry_price","type":"numeric","format":{"specifier":".5f"}},
        {"name":"Exit Price","id":"exit_price","type":"numeric","format":{"specifier":".5f"}},
        {"name":"Profit (USD)","id":"profit_usd","type":"numeric","format":{"specifier":".2f"}},
        {"name":"Profit (%)","id":"profit_pct","type":"numeric","format":{"specifier":".2f"}},
        {"name":"Leverage","id":"leverage","type":"numeric"},
        {"name":"Shadow?","id":"shadow_tag"}
    ]
    return dash_table.DataTable(
        id="trade-history-table",
        columns=cols,
        data=df.to_dict("records"),
        sort_action="native",
        filter_action="native",
        page_action="native",
        page_size=20,
        style_table={"height":"500px","overflowY":"auto"},
        style_cell={"padding":"8px","backgroundColor":"#0f1217","color":"#e8eaed"},
        style_header={"backgroundColor":"#1b1f2a","fontWeight":"bold"},
        style_data_conditional=[
            {"if":{"filter_query":"{profit_usd} > 0"},"backgroundColor":"#0f2d0f","color":"#00ff00"},
            {"if":{"filter_query":"{profit_usd} < 0"},"backgroundColor":"#2d0f0f","color":"#ff4d4d"},
            {"if":{"filter_query":"{profit_usd} = 0"},"backgroundColor":"#1b1f2a","color":"#888"},
            {"if":{"filter_query":"{shadow_tag} = true"},"border":"2px solid #ffa500"}
        ]
    )
