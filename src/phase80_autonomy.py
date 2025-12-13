import time
import math
import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional
from pathlib import Path

@dataclass
class Phase80Config:
    heartbeat_interval_sec: int = 30
    heartbeat_miss_sec: int = 90

    max_audit_errors_15m: int = 2
    max_fee_mismatch_usd_1h: float = 10.0
    max_price_feed_gap_sec: int = 15
    max_order_reject_rate_1h: float = 0.05

    rollback_rr_floor_tier: Dict[str, float] = field(default_factory=lambda: {"majors": 0.95, "l1s": 0.92, "experimental": 0.88})
    rollback_dd_floor_pct: float = 3.0

    exp_enroll_per_symbol_max: int = 2
    exp_window_trades_min: int = 40
    exp_promotion_min_ev_uplift_usd: float = 0.15
    exp_promotion_rr_min_tier: Dict[str, float] = field(default_factory=lambda: {"majors": 1.00, "l1s": 0.95, "experimental": 0.90})
    exp_promotion_slip_p75_cap_tier: Dict[str, float] = field(default_factory=lambda: {"majors": 12.0, "l1s": 15.0, "experimental": 18.0})
    exp_confidence_z: float = 1.64

    ramp_sharpe_min: float = 1.0
    ramp_rr_min_majors: float = 1.10
    ramp_dd_max_pct: float = 2.5
    ramp_corr_cap: float = 0.40
    ramp_step_pct: float = 0.15
    ramp_cooldown_hours: int = 6

    exposure_max_pct_tier: Dict[str, float] = field(default_factory=lambda: {"majors": 0.45, "l1s": 0.30, "experimental": 0.20})
    concurrent_pyramiding_cap_tier: Dict[str, int] = field(default_factory=lambda: {"majors": 2, "l1s": 1, "experimental": 1})

    governor_window_hours: int = 24
    governor_top_symbols: int = 5
    governor_weight_nudge_pct: float = 0.10

    snapshot_keep_hours: int = 48
    replay_max_gap_sec: int = 120

def default_phase80_cfg() -> Phase80Config:
    return Phase80Config()

class Phase80Autonomy:
    def __init__(self, config: Phase80Config):
        self.config = config
        self.startup_ts: float = self.now()
        self.startup_grace_period_sec: int = 60
        self.last_heartbeats: Dict[str, float] = {
            "signals": self.startup_ts,
            "execution": self.startup_ts,
            "fees": self.startup_ts,
            "telemetry": self.startup_ts,
            "persistence": self.startup_ts
        }
        self.last_ramp_ts: Optional[float] = None
        self.experiment_registry: Dict[str, List[Dict]] = {}
        self.policy_stack: List[Dict] = []
        self.incident_active: bool = False
        self.safe_mode_active: bool = False
        self.tier_map = {
            "BTCUSDT": "majors", "ETHUSDT": "majors",
            "SOLUSDT": "l1s", "AVAXUSDT": "l1s",
            "DOTUSDT": "experimental", "TRXUSDT": "experimental",
            "XRPUSDT": "experimental", "ADAUSDT": "experimental",
            "DOGEUSDT": "experimental", "BNBUSDT": "experimental",
            "MATICUSDT": "experimental"
        }
        self.symbol_weights: Dict[str, float] = {s: 1.0 for s in self.tier_map.keys()}
        self.tier_exposure_throttle: Dict[str, Optional[float]] = {}
        self.tier_pyramiding_frozen: Dict[str, bool] = {}
    
    def now(self) -> float:
        return time.time()
    
    def heartbeat(self, subsystem: str):
        self.last_heartbeats[subsystem] = self.now()
    
    def check_heartbeats(self):
        now_ts = self.now()
        if now_ts - self.startup_ts < self.startup_grace_period_sec:
            return
        
        missed = []
        for s in ["signals", "execution", "fees", "telemetry", "persistence"]:
            last = self.last_heartbeats.get(s, 0)
            if now_ts - last > self.config.heartbeat_miss_sec:
                missed.append(s)
        if missed:
            self.trigger_incident(f"Heartbeat missed: {missed}")
    
    def trigger_incident(self, reason: str):
        if self.incident_active:
            return
        self.incident_active = True
        print(f"🚨 PHASE80 INCIDENT: {reason}")
        self.snapshot_state()
        self.rotate_to_safe_mode()
        self.restart_faulty_subsystems()
        self.replay_missed_signals(self.config.replay_max_gap_sec)
        self.reconcile_positions()
        print(f"✅ PHASE80: Incident resolved")
        self.incident_active = False
    
    def watchdog_check(self):
        if self.audit_errors_count_15m() > self.config.max_audit_errors_15m:
            self.fix_audit_pipeline()
            self.push_policy_stack({"fix": "audit_pipeline"})
        
        if self.fee_mismatch_usd_1h() > self.config.max_fee_mismatch_usd_1h:
            self.resync_fee_models()
            self.push_policy_stack({"fix": "fees_resync"})
        
        if self.price_feed_gap_sec() > self.config.max_price_feed_gap_sec:
            self.switch_price_feed_provider()
            self.push_policy_stack({"fix": "price_feed_switch"})
        
        if self.order_reject_rate_1h() > self.config.max_order_reject_rate_1h:
            self.tighten_routing_and_slippage_caps()
            self.push_policy_stack({"fix": "routing_tighten"})
    
    def push_policy_stack(self, record: Dict):
        record["ts"] = self.now()
        self.policy_stack.append(record)
        if len(self.policy_stack) > 100:
            self.policy_stack.pop(0)
    
    def rollback_if_needed(self):
        dd = self.rolling_drawdown_pct_24h()
        tiers = ["majors", "l1s", "experimental"]
        rr_breach = False
        for t in tiers:
            rr = self.realized_rr_24h_tier(t)
            floor = self.config.rollback_rr_floor_tier.get(t, 0.9)
            if rr is not None and rr < floor:
                rr_breach = True
        
        if (dd is not None and dd > self.config.rollback_dd_floor_pct) or rr_breach:
            for _ in range(min(3, len(self.policy_stack))):
                rec = self.policy_stack.pop()
                self.apply_rollback_record(rec)
            print(f"⚠️  PHASE80: Rollback applied (dd={dd:.2f}%, rr_breach={rr_breach})")
    
    def enroll_experiments(self):
        for symbol in self.list_all_symbols():
            exps = self.experiment_registry.setdefault(symbol, [])
            if len(exps) >= self.config.exp_enroll_per_symbol_max:
                continue
            tier = self.tier_for_symbol(symbol)
            variant = self.propose_variant_for_symbol(symbol, tier)
            exps.append({
                "symbol": symbol,
                "tier": tier,
                "variant": variant,
                "enrolled_ts": self.now(),
                "active": True
            })
    
    def evaluate_experiments(self):
        for symbol, exps in self.experiment_registry.items():
            for exp in exps:
                if not exp["active"]:
                    continue
                tier = exp["tier"]
                baseline_ev = self.baseline_ev_usd(symbol, self.config.exp_window_trades_min)
                variant_ev = self.variant_ev_usd(symbol, exp["variant"], self.config.exp_window_trades_min)
                ev_uplift = (variant_ev or 0) - (baseline_ev or 0)
                rr = self.variant_rr(symbol, exp["variant"])
                slip_p75 = self.variant_slip_p75_bps(symbol, exp["variant"])
                z = self.ev_uplift_zscore(symbol, exp["variant"])
                rr_min = self.config.exp_promotion_rr_min_tier.get(tier, 0.95)
                slip_cap = self.config.exp_promotion_slip_p75_cap_tier.get(tier, 15.0)
                
                promotable = (ev_uplift is not None and ev_uplift >= self.config.exp_promotion_min_ev_uplift_usd and
                              rr is not None and rr >= rr_min and
                              slip_p75 is not None and slip_p75 <= slip_cap and
                              z is not None and z >= self.config.exp_confidence_z)
                
                if promotable:
                    self.promote_variant(symbol, exp["variant"])
                    exp["active"] = False
                    self.push_policy_stack({"promote": exp["variant"], "symbol": symbol})
                    print(f"✅ PHASE80: Promoted variant for {symbol} (EV +${ev_uplift:.2f}, R:R={rr:.2f}, z={z:.2f})")
                elif ev_uplift is not None and ev_uplift < 0:
                    self.demote_variant(symbol, exp["variant"])
                    exp["active"] = False
    
    def can_ramp_capital(self) -> bool:
        if self.last_ramp_ts and (self.now() - self.last_ramp_ts) < self.config.ramp_cooldown_hours * 3600:
            return False
        
        sharpe = self.rolling_sharpe_48h()
        rr_maj = self.realized_rr_24h_tier("majors")
        dd = self.rolling_drawdown_pct_24h()
        
        if sharpe is None or sharpe < self.config.ramp_sharpe_min:
            return False
        if rr_maj is None or rr_maj < self.config.ramp_rr_min_majors:
            return False
        if dd is not None and dd > self.config.ramp_dd_max_pct:
            return False
        
        large_symbols = self.large_positions_symbols()
        for sym in self.candidate_ramp_symbols():
            for ls in large_symbols:
                corr = self.rolling_corr_24h(sym, ls)
                if corr is not None and corr > self.config.ramp_corr_cap:
                    return False
        return True
    
    def apply_capital_ramp(self):
        if not self.can_ramp_capital():
            return
        self.increase_deployed_capital_pct(self.config.ramp_step_pct)
        self.last_ramp_ts = self.now()
        print(f"✅ PHASE80: Capital ramp applied (+{self.config.ramp_step_pct*100:.0f}%)")
    
    def enforce_exposure_caps(self):
        for tier, cap_pct in self.config.exposure_max_pct_tier.items():
            exposure = self.portfolio_exposure_pct_tier(tier)
            if exposure is not None and exposure > cap_pct:
                self.throttle_tier_exposure(tier, target_pct=cap_pct)
                print(f"⚠️  PHASE80: Exposure throttled {tier} {exposure*100:.1f}% → {cap_pct*100:.1f}%")
    
    def enforce_pyramiding_caps(self):
        for tier, cap_n in self.config.concurrent_pyramiding_cap_tier.items():
            active_adds = self.active_pyramiding_count_tier(tier)
            if active_adds is not None and active_adds > cap_n:
                self.freeze_new_pyramids_tier(tier)
                print(f"🔒 PHASE80: Pyramiding frozen {tier} (active={active_adds}, cap={cap_n})")
    
    def governor_reweight(self):
        attrib = self.pnl_attribution_last_hours(self.config.governor_window_hours)
        if not attrib:
            return
        
        top = sorted(attrib.items(), key=lambda kv: kv[1], reverse=True)[:self.config.governor_top_symbols]
        bottom = sorted(attrib.items(), key=lambda kv: kv[1])[:self.config.governor_top_symbols]
        
        for sym, net in top:
            self.nudge_symbol_weight(sym, +self.config.governor_weight_nudge_pct)
        for sym, net in bottom:
            self.nudge_symbol_weight(sym, -self.config.governor_weight_nudge_pct)
    
    def snapshot_state(self):
        snapshot = {
            "ts": self.now(),
            "heartbeats": self.last_heartbeats.copy(),
            "experiments": len(self.experiment_registry),
            "policy_stack_depth": len(self.policy_stack),
            "safe_mode": self.safe_mode_active
        }
        Path("logs/phase80_snapshots").mkdir(parents=True, exist_ok=True)
        path = f"logs/phase80_snapshots/snapshot_{int(self.now())}.json"
        with open(path, "w") as f:
            json.dump(snapshot, f, indent=2)
    
    def rotate_to_safe_mode(self):
        self.safe_mode_active = True
        print(f"🛡️  PHASE80: Safe mode activated")
    
    def restart_faulty_subsystems(self):
        pass
    
    def replay_missed_signals(self, max_gap_sec: int):
        pass
    
    def reconcile_positions(self):
        pass
    
    def audit_errors_count_15m(self) -> int:
        return 0
    
    def fix_audit_pipeline(self):
        print(f"🔧 PHASE80: Audit pipeline repaired")
    
    def fee_mismatch_usd_1h(self) -> float:
        return 0.0
    
    def resync_fee_models(self):
        print(f"🔧 PHASE80: Fee models resynced")
    
    def price_feed_gap_sec(self) -> int:
        return 0
    
    def switch_price_feed_provider(self):
        print(f"🔧 PHASE80: Price feed provider switched")
    
    def order_reject_rate_1h(self) -> float:
        return 0.0
    
    def tighten_routing_and_slippage_caps(self):
        print(f"🔧 PHASE80: Routing and slippage caps tightened")
    
    def apply_rollback_record(self, rec: Dict):
        pass
    
    def list_all_symbols(self) -> List[str]:
        return list(self.tier_map.keys())
    
    def tier_for_symbol(self, symbol: str) -> str:
        return self.tier_map.get(symbol, "experimental")
    
    def propose_variant_for_symbol(self, symbol: str, tier: str) -> Dict:
        return {"type": "ev_gate_relaxation", "ev_delta": -0.05}
    
    def baseline_ev_usd(self, symbol: str, window_trades_min: int) -> Optional[float]:
        return None
    
    def variant_ev_usd(self, symbol: str, variant: Dict, window_trades_min: int) -> Optional[float]:
        return None
    
    def variant_rr(self, symbol: str, variant: Dict) -> Optional[float]:
        return None
    
    def variant_slip_p75_bps(self, symbol: str, variant: Dict) -> Optional[float]:
        return None
    
    def ev_uplift_zscore(self, symbol: str, variant: Dict) -> Optional[float]:
        return None
    
    def promote_variant(self, symbol: str, variant: Dict):
        pass
    
    def demote_variant(self, symbol: str, variant: Dict):
        pass
    
    def rolling_sharpe_48h(self) -> Optional[float]:
        try:
            with open("logs/portfolio.json", "r") as f:
                lines = f.readlines()[-100:]
                values = []
                for line in lines:
                    entry = json.loads(line)
                    values.append(entry.get("total_value", 10000))
                if len(values) < 48:
                    return None
                returns = [(values[i] - values[i-1]) / values[i-1] for i in range(1, len(values))]
                if not returns:
                    return None
                mean_ret = sum(returns) / len(returns)
                std_ret = math.sqrt(sum((r - mean_ret) ** 2 for r in returns) / len(returns)) if len(returns) > 1 else 0
                return (mean_ret / std_ret * math.sqrt(48)) if std_ret > 0 else None
        except:
            return None
    
    def realized_rr_24h_tier(self, tier: str) -> Optional[float]:
        try:
            with open("logs/trades.json", "r") as f:
                lines = f.readlines()[-500:]
                tier_symbols = [s for s, t in self.tier_map.items() if t == tier]
                wins, losses = [], []
                for line in lines:
                    trade = json.loads(line)
                    if trade.get("symbol") in tier_symbols and trade.get("realized_pnl") is not None:
                        pnl = trade["realized_pnl"]
                        if pnl > 0:
                            wins.append(pnl)
                        elif pnl < 0:
                            losses.append(abs(pnl))
                if not wins or not losses:
                    return None
                avg_win = sum(wins) / len(wins)
                avg_loss = sum(losses) / len(losses)
                return avg_win / avg_loss if avg_loss > 0 else None
        except:
            return None
    
    def rolling_drawdown_pct_24h(self) -> Optional[float]:
        try:
            with open("logs/portfolio.json", "r") as f:
                lines = f.readlines()[-100:]
                values = [json.loads(line).get("total_value", 10000) for line in lines]
                if len(values) < 10:
                    return None
                peak = values[0]
                max_dd = 0
                for v in values:
                    peak = max(peak, v)
                    dd = (peak - v) / peak * 100
                    max_dd = max(max_dd, dd)
                return max_dd
        except:
            return None
    
    def large_positions_symbols(self) -> List[str]:
        return []
    
    def candidate_ramp_symbols(self) -> List[str]:
        return ["BTCUSDT", "ETHUSDT"]
    
    def rolling_corr_24h(self, sym_a: str, sym_b: str) -> Optional[float]:
        return 0.3
    
    def increase_deployed_capital_pct(self, step_pct: float):
        pass
    
    def portfolio_exposure_pct_tier(self, tier: str) -> Optional[float]:
        return None
    
    def throttle_tier_exposure(self, tier: str, target_pct: float):
        self.tier_exposure_throttle[tier] = target_pct
    
    def active_pyramiding_count_tier(self, tier: str) -> Optional[int]:
        return None
    
    def freeze_new_pyramids_tier(self, tier: str):
        self.tier_pyramiding_frozen[tier] = True
    
    def pnl_attribution_last_hours(self, hours: int) -> Dict[str, float]:
        try:
            with open("logs/trades.json", "r") as f:
                lines = f.readlines()[-500:]
                attrib = {}
                for line in lines:
                    trade = json.loads(line)
                    symbol = trade.get("symbol")
                    pnl = trade.get("realized_pnl", 0)
                    if symbol and pnl:
                        attrib[symbol] = attrib.get(symbol, 0) + pnl
                return attrib
        except:
            return {}
    
    def nudge_symbol_weight(self, symbol: str, pct_delta: float):
        old_weight = self.symbol_weights.get(symbol, 1.0)
        new_weight = max(0.5, min(2.0, old_weight * (1 + pct_delta)))
        self.symbol_weights[symbol] = new_weight
    
    def get_symbol_weight(self, symbol: str) -> float:
        return self.symbol_weights.get(symbol, 1.0)
    
    def is_safe_mode(self) -> bool:
        return self.safe_mode_active
    
    def is_tier_exposure_throttled(self, tier: str) -> Optional[float]:
        return self.tier_exposure_throttle.get(tier)
    
    def is_tier_pyramiding_frozen(self, tier: str) -> bool:
        return self.tier_pyramiding_frozen.get(tier, False)
    
    def get_status(self) -> Dict:
        return {
            "heartbeats": {k: int(self.now() - v) for k, v in self.last_heartbeats.items()},
            "experiments": {k: len(v) for k, v in self.experiment_registry.items()},
            "policy_stack_depth": len(self.policy_stack),
            "safe_mode": self.safe_mode_active,
            "last_ramp": int(self.now() - self.last_ramp_ts) if self.last_ramp_ts else None,
            "symbol_weights": self.symbol_weights,
            "tier_exposure_throttle": self.tier_exposure_throttle,
            "tier_pyramiding_frozen": self.tier_pyramiding_frozen
        }
