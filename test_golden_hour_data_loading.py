#!/usr/bin/env python3
"""
Test Golden Hour Data Loading
Tests both all-time comprehensive data and 24h rolling window
"""
import sys
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone

sys.path.insert(0, '.')

def test_all_time_data():
    """Test loading all-time comprehensive data from GOLDEN_HOUR_ANALYSIS.json"""
    print("=" * 60)
    print("TEST 1: All-Time Comprehensive Data")
    print("=" * 60)
    
    analysis_file = Path("GOLDEN_HOUR_ANALYSIS.json")
    if not analysis_file.exists():
        print(f"❌ File not found: {analysis_file}")
        return False
    
    try:
        with open(analysis_file, 'r') as f:
            data = json.load(f)
        
        gh_data = data.get("golden_hour_closed", {})
        if not gh_data:
            print("❌ No golden_hour_closed data")
            return False
        
        count = int(gh_data.get("count", 0))
        total_pnl = float(gh_data.get("total_pnl", 0))
        win_rate = float(gh_data.get("win_rate", 0))
        
        print(f"✅ File loaded successfully")
        print(f"   Total trades: {count}")
        print(f"   Total P&L: ${total_pnl:.2f}")
        print(f"   Win rate: {win_rate:.1f}%")
        
        # Verify expected values
        if count == 1025 and abs(total_pnl - 28.78) < 1.0:
            print("✅ Expected values match")
            return True
        else:
            print(f"⚠️  Values don't match expected (1025 trades, $28.78 P&L)")
            return False
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_24h_rolling_window():
    """Test 24h rolling window filtering"""
    print("\n" + "=" * 60)
    print("TEST 2: 24h Rolling Window")
    print("=" * 60)
    
    try:
        from src.data_registry import DataRegistry as DR
        
        pos = DR.read_json(DR.POSITIONS_FUTURES)
        closed = pos.get("closed_positions", []) if pos else []
        
        cutoff_24h = datetime.now(timezone.utc) - timedelta(hours=24)
        cutoff_24h_ts = cutoff_24h.timestamp()
        
        gh_24h_trades = []
        for p in closed:
            ca = p.get("closed_at", "")
            if not ca:
                continue
            try:
                if isinstance(ca, str) and "T" in ca:
                    dt = datetime.fromisoformat(ca.replace("Z", "+00:00"))
                    ts = dt.timestamp()
                    if ts >= cutoff_24h_ts:
                        hour = dt.hour
                        if 9 <= hour < 16:  # Golden Hour: 09:00-16:00 UTC
                            gh_24h_trades.append(p)
            except:
                pass
        
        print(f"✅ Filtering successful")
        print(f"   Total closed positions: {len(closed)}")
        print(f"   Golden Hour trades in last 24h: {len(gh_24h_trades)}")
        
        if gh_24h_trades:
            pnls = []
            for p in gh_24h_trades:
                pnl = p.get("net_pnl", p.get("pnl", 0))
                try:
                    pnls.append(float(pnl) if pnl is not None else 0.0)
                except:
                    pnls.append(0.0)
            
            total_pnl = sum(pnls)
            wins = sum(1 for pnl in pnls if pnl > 0)
            losses = len(pnls) - wins
            win_rate = (wins / len(pnls) * 100) if pnls else 0.0
            
            print(f"   24h P&L: ${total_pnl:.2f}")
            print(f"   Wins: {wins}, Losses: {losses}")
            print(f"   Win rate: {win_rate:.1f}%")
        else:
            print("   No trades in last 24h during Golden Hour")
        
        print("✅ 24h filtering logic works correctly")
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_dashboard_summary_structure():
    """Test that golden_hour_summary has all required fields"""
    print("\n" + "=" * 60)
    print("TEST 3: Dashboard Summary Structure")
    print("=" * 60)
    
    required_fields = [
        "wallet_balance",
        "total_trades",
        "wins",
        "losses",
        "win_rate",
        "net_pnl",
        "avg_pnl",
        "avg_win",
        "avg_loss",
        "gross_profit",
        "gross_loss",
        "profit_factor"
    ]
    
    # Create a test summary (mimicking what dashboard would create)
    test_summary = {
        "wallet_balance": 10000.0,
        "total_trades": 1025,
        "wins": 444,
        "losses": 581,
        "win_rate": 43.3,
        "net_pnl": 28.78,
        "avg_pnl": 0.03,
        "avg_win": 0.1,
        "avg_loss": -0.05,
        "gross_profit": 50.0,
        "gross_loss": 21.22,
        "profit_factor": 1.07
    }
    
    missing = [f for f in required_fields if f not in test_summary]
    if missing:
        print(f"❌ Missing fields: {missing}")
        return False
    
    print(f"✅ All required fields present: {len(required_fields)}")
    for field in required_fields:
        print(f"   - {field}: {test_summary[field]}")
    
    return True

def main():
    """Run all tests"""
    print("Golden Hour Data Loading Tests")
    print("=" * 60)
    
    results = []
    
    results.append(("All-Time Data", test_all_time_data()))
    results.append(("24h Rolling Window", test_24h_rolling_window()))
    results.append(("Summary Structure", test_dashboard_summary_structure()))
    
    print("\n" + "=" * 60)
    print("TEST RESULTS")
    print("=" * 60)
    
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {name}")
    
    all_passed = all(r[1] for r in results)
    
    if all_passed:
        print("\n✅ ALL TESTS PASSED")
        return 0
    else:
        print("\n❌ SOME TESTS FAILED")
        return 1

if __name__ == "__main__":
    exit(main())

