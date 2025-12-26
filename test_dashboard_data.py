#!/usr/bin/env python3
"""Test dashboard data loading."""
import sys
sys.path.insert(0, ".")

from src.data_registry import DataRegistry as DR
from datetime import datetime, timedelta

print("Testing dashboard data loading...")
print("=" * 60)

# Check closed positions
positions_data = DR.read_json(DR.POSITIONS_FUTURES)
all_closed = positions_data.get("closed_positions", []) if positions_data else []
print(f"Total closed positions: {len(all_closed)}")

# Check last 24 hours
cutoff = datetime.utcnow() - timedelta(hours=24)
cutoff_ts = cutoff.timestamp()
recent_24h = []

for pos in all_closed[-100:]:  # Check last 100
    closed_at = pos.get("closed_at", "")
    if not closed_at:
        continue
    try:
        if isinstance(closed_at, str):
            if "T" in closed_at:
                closed_dt = datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
            else:
                closed_dt = datetime.strptime(closed_at, "%Y-%m-%d %H:%M:%S")
            closed_ts = closed_dt.timestamp()
        else:
            closed_ts = float(closed_at)
        
        if closed_ts >= cutoff_ts:
            pnl = pos.get("pnl") or pos.get("net_pnl") or pos.get("realized_pnl") or 0
            recent_24h.append({
                "symbol": pos.get("symbol", "?"),
                "pnl": pnl,
                "closed_at": closed_at
            })
    except Exception as e:
        pass

print(f"\nPositions in last 24h: {len(recent_24h)}")
if recent_24h:
    total_pnl = sum(p.get("pnl", 0) for p in recent_24h)
    print(f"Total P&L (last 24h): ${total_pnl:.2f}")
    print("\nSample positions:")
    for p in recent_24h[:5]:
        print(f"  {p['symbol']}: ${p['pnl']:.2f} @ {p['closed_at']}")
else:
    print("\n⚠️ No positions found in last 24 hours!")
    if all_closed:
        print(f"\nLast closed position:")
        last = all_closed[-1]
        print(f"  Symbol: {last.get('symbol', '?')}")
        print(f"  Closed at: {last.get('closed_at', '?')}")
        print(f"  P&L: {last.get('pnl', last.get('net_pnl', '?'))}")

