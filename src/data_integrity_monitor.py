"""
Data Integrity Monitor - Catches test data pollution and anomalies before they reach the user.

Validates:
1. No test trades (PHASE82, TEST, DRILL, etc.) in production portfolio
2. No impossible P&L swings (>20% loss in <1 hour)
3. No fake positions in open_positions
4. Consistent data between portfolio.json and positions.json

Triggers alerts when integrity violations detected.
"""
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
import pytz

ARIZONA_TZ = pytz.timezone('America/Phoenix')

PORTFOLIO_FILE = Path("logs/portfolio.json")
POSITIONS_FILE = Path("logs/positions.json")
INTEGRITY_LOG = Path("logs/data_integrity_events.jsonl")

# Test/fake trade detection patterns
TEST_PATTERNS = [
    "PHASE82",
    "TEST",
    "DRILL",
    "VALIDATION",
    "FAKE",
    "MOCK",
    "DUMMY"
]

# Anomaly thresholds
MAX_HOURLY_LOSS_PCT = 20.0  # >20% loss in 1 hour is impossible in normal trading
MAX_SINGLE_TRADE_LOSS_PCT = 15.0  # Single trade >15% loss is suspicious
MIN_TRADE_DURATION_SEC = 10  # Trades <10s are likely test trades

class IntegrityViolation:
    def __init__(self, severity: str, category: str, description: str, details: Dict):
        self.severity = severity  # CRITICAL, WARNING, INFO
        self.category = category  # test_pollution, anomaly, inconsistency
        self.description = description
        self.details = details
        self.timestamp = time.time()
    
    def to_dict(self):
        return {
            "severity": self.severity,
            "category": self.category,
            "description": self.description,
            "details": self.details,
            "timestamp": self.timestamp
        }

def _log_violation(violation: IntegrityViolation):
    """Log integrity violation to JSONL file."""
    INTEGRITY_LOG.parent.mkdir(exist_ok=True)
    with open(INTEGRITY_LOG, 'a') as f:
        f.write(json.dumps(violation.to_dict()) + '\n')
    
    # Print to console based on severity
    if violation.severity == "CRITICAL":
        print(f"🚨 DATA INTEGRITY CRITICAL: {violation.description}")
        print(f"   Details: {violation.details}")
    elif violation.severity == "WARNING":
        print(f"⚠️  DATA INTEGRITY WARNING: {violation.description}")

def check_test_pollution() -> List[IntegrityViolation]:
    """Check for test/fake trades in production portfolio."""
    violations = []
    
    if not PORTFOLIO_FILE.exists():
        return violations
    
    try:
        with open(PORTFOLIO_FILE, 'r') as f:
            data = json.load(f)
        
        trades = data.get('trades', [])
        test_trades = []
        
        for trade in trades:
            strategy = trade.get('strategy', '')
            symbol = trade.get('symbol', '')
            
            # Check if trade matches test patterns
            for pattern in TEST_PATTERNS:
                if pattern in strategy.upper() or pattern in symbol.upper():
                    test_trades.append(trade)
                    break
        
        if test_trades:
            violations.append(IntegrityViolation(
                severity="CRITICAL",
                category="test_pollution",
                description=f"Found {len(test_trades)} test trades in production portfolio",
                details={
                    "test_trade_count": len(test_trades),
                    "total_trades": len(trades),
                    "examples": [
                        {
                            "symbol": t.get('symbol'),
                            "strategy": t.get('strategy'),
                            "roi": t.get('roi_pct')
                        }
                        for t in test_trades[:5]
                    ]
                }
            ))
    except Exception as e:
        violations.append(IntegrityViolation(
            severity="WARNING",
            category="check_failure",
            description=f"Failed to check test pollution: {str(e)}",
            details={"error": str(e)}
        ))
    
    return violations

def check_test_positions() -> List[IntegrityViolation]:
    """Check for test positions in open_positions."""
    violations = []
    
    if not POSITIONS_FILE.exists():
        return violations
    
    try:
        with open(POSITIONS_FILE, 'r') as f:
            data = json.load(f)
        
        positions = data.get('open_positions', [])
        test_positions = []
        
        for pos in positions:
            strategy = pos.get('strategy', '')
            
            for pattern in TEST_PATTERNS:
                if pattern in strategy.upper():
                    test_positions.append(pos)
                    break
        
        if test_positions:
            violations.append(IntegrityViolation(
                severity="CRITICAL",
                category="test_pollution",
                description=f"Found {len(test_positions)} test positions in production",
                details={
                    "test_position_count": len(test_positions),
                    "examples": [
                        {
                            "symbol": p.get('symbol'),
                            "strategy": p.get('strategy')
                        }
                        for p in test_positions[:5]
                    ]
                }
            ))
    except Exception as e:
        violations.append(IntegrityViolation(
            severity="WARNING",
            category="check_failure",
            description=f"Failed to check test positions: {str(e)}",
            details={"error": str(e)}
        ))
    
    return violations

def check_impossible_losses() -> List[IntegrityViolation]:
    """Detect impossible P&L swings that indicate fake trades."""
    violations = []
    
    if not PORTFOLIO_FILE.exists():
        return violations
    
    try:
        with open(PORTFOLIO_FILE, 'r') as f:
            data = json.load(f)
        
        trades = data.get('trades', [])
        closed_trades = [t for t in trades if t.get('action') == 'close']
        
        # Check last 100 closed trades for anomalies
        recent_trades = closed_trades[-100:]
        anomalies = []
        
        for trade in recent_trades:
            roi = trade.get('roi_pct', 0)
            timestamp = trade.get('timestamp', '')
            opened_at = trade.get('opened_at', timestamp)
            
            # Check for extreme losses
            if roi < -MAX_SINGLE_TRADE_LOSS_PCT:
                anomalies.append({
                    "symbol": trade.get('symbol'),
                    "strategy": trade.get('strategy'),
                    "roi": roi,
                    "reason": "extreme_loss"
                })
                continue
            
            # Check for impossibly short trades with large losses
            try:
                opened_time = datetime.fromisoformat(opened_at.replace('Z', '+00:00'))
                closed_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                duration_sec = (closed_time - opened_time).total_seconds()
                
                if duration_sec < MIN_TRADE_DURATION_SEC and abs(roi) > 1.0:
                    anomalies.append({
                        "symbol": trade.get('symbol'),
                        "strategy": trade.get('strategy'),
                        "roi": roi,
                        "duration_sec": duration_sec,
                        "reason": "instant_large_move"
                    })
            except:
                pass
        
        if anomalies:
            violations.append(IntegrityViolation(
                severity="CRITICAL" if len(anomalies) > 10 else "WARNING",
                category="anomaly",
                description=f"Found {len(anomalies)} trades with impossible P&L patterns",
                details={
                    "anomaly_count": len(anomalies),
                    "examples": anomalies[:10]
                }
            ))
    except Exception as e:
        violations.append(IntegrityViolation(
            severity="WARNING",
            category="check_failure",
            description=f"Failed to check impossible losses: {str(e)}",
            details={"error": str(e)}
        ))
    
    return violations

def check_portfolio_health() -> List[IntegrityViolation]:
    """Check overall portfolio health for suspicious patterns."""
    violations = []
    
    if not PORTFOLIO_FILE.exists():
        return violations
    
    try:
        with open(PORTFOLIO_FILE, 'r') as f:
            data = json.load(f)
        
        portfolio = data.get('portfolio', {})
        trades = data.get('trades', [])
        
        current_value = portfolio.get('total_value', 0)
        peak_value = portfolio.get('peak_value', 0)
        
        # Check for massive unexplained drawdown
        if peak_value > 5000 and current_value > 0:
            drawdown_pct = ((peak_value - current_value) / peak_value * 100)
            
            if drawdown_pct > 30:
                # Check if this is explained by real losses
                recent_trades = [t for t in trades[-50:] if t.get('action') == 'close']
                recent_losses = sum(t.get('pnl', 0) for t in recent_trades if t.get('pnl', 0) < 0)
                expected_drawdown = abs(recent_losses) / peak_value * 100 if peak_value > 0 else 0
                
                if drawdown_pct > expected_drawdown * 2:
                    violations.append(IntegrityViolation(
                        severity="CRITICAL",
                        category="anomaly",
                        description=f"Unexplained {drawdown_pct:.1f}% drawdown detected",
                        details={
                            "current_value": current_value,
                            "peak_value": peak_value,
                            "drawdown_pct": drawdown_pct,
                            "expected_drawdown_pct": expected_drawdown,
                            "recent_losses": recent_losses
                        }
                    ))
    except Exception as e:
        violations.append(IntegrityViolation(
            severity="WARNING",
            category="check_failure",
            description=f"Failed to check portfolio health: {str(e)}",
            details={"error": str(e)}
        ))
    
    return violations

def run_full_integrity_check() -> Dict:
    """Run all integrity checks and return summary."""
    all_violations = []
    
    # Run all checks
    all_violations.extend(check_test_pollution())
    all_violations.extend(check_test_positions())
    all_violations.extend(check_impossible_losses())
    all_violations.extend(check_portfolio_health())
    
    # Log all violations
    for violation in all_violations:
        _log_violation(violation)
    
    # Categorize by severity
    critical = [v for v in all_violations if v.severity == "CRITICAL"]
    warnings = [v for v in all_violations if v.severity == "WARNING"]
    
    summary = {
        "timestamp": time.time(),
        "total_violations": len(all_violations),
        "critical_count": len(critical),
        "warning_count": len(warnings),
        "critical": [v.to_dict() for v in critical],
        "warnings": [v.to_dict() for v in warnings],
        "status": "CRITICAL" if critical else ("WARNING" if warnings else "HEALTHY")
    }
    
    return summary

def auto_clean_test_data() -> Dict:
    """Automatically remove test trades from portfolio (safe operation)."""
    removed = {
        "trades_removed": 0,
        "positions_removed": 0
    }
    
    # Clean portfolio trades
    if PORTFOLIO_FILE.exists():
        try:
            with open(PORTFOLIO_FILE, 'r') as f:
                data = json.load(f)
            
            original_count = len(data.get('trades', []))
            
            # Filter out test trades
            clean_trades = []
            for trade in data.get('trades', []):
                is_test = False
                strategy = trade.get('strategy', '')
                symbol = trade.get('symbol', '')
                
                for pattern in TEST_PATTERNS:
                    if pattern in strategy.upper() or pattern in symbol.upper():
                        is_test = True
                        break
                
                if not is_test:
                    clean_trades.append(trade)
            
            data['trades'] = clean_trades
            
            with open(PORTFOLIO_FILE, 'w') as f:
                json.dump(data, f, indent=2)
            
            removed['trades_removed'] = original_count - len(clean_trades)
        except Exception as e:
            print(f"⚠️  Failed to clean portfolio trades: {e}")
    
    # Clean test positions
    if POSITIONS_FILE.exists():
        try:
            with open(POSITIONS_FILE, 'r') as f:
                data = json.load(f)
            
            original_count = len(data.get('open_positions', []))
            
            # Filter out test positions
            clean_positions = []
            for pos in data.get('open_positions', []):
                is_test = False
                strategy = pos.get('strategy', '')
                
                for pattern in TEST_PATTERNS:
                    if pattern in strategy.upper():
                        is_test = True
                        break
                
                if not is_test:
                    clean_positions.append(pos)
            
            data['open_positions'] = clean_positions
            
            with open(POSITIONS_FILE, 'w') as f:
                json.dump(data, f, indent=2)
            
            removed['positions_removed'] = original_count - len(clean_positions)
        except Exception as e:
            print(f"⚠️  Failed to clean test positions: {e}")
    
    if removed['trades_removed'] > 0 or removed['positions_removed'] > 0:
        print(f"🧹 Auto-cleaned test data: {removed['trades_removed']} trades, {removed['positions_removed']} positions")
    
    return removed

if __name__ == "__main__":
    print("🔍 Running Data Integrity Check...\n")
    summary = run_full_integrity_check()
    
    print(f"\n{'='*80}")
    print(f"Data Integrity Status: {summary['status']}")
    print(f"{'='*80}")
    print(f"Total violations: {summary['total_violations']}")
    print(f"Critical: {summary['critical_count']}")
    print(f"Warnings: {summary['warning_count']}")
    
    if summary['critical']:
        print(f"\n🚨 CRITICAL ISSUES:")
        for v in summary['critical']:
            print(f"   • {v['description']}")
    
    if summary['warnings']:
        print(f"\n⚠️  WARNINGS:")
        for v in summary['warnings']:
            print(f"   • {v['description']}")
    
    if summary['status'] == "HEALTHY":
        print(f"\n✅ All integrity checks passed!")
    else:
        print(f"\n🔧 Run auto_clean_test_data() to fix test pollution issues")
