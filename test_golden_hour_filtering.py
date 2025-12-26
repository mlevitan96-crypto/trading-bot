#!/usr/bin/env python3
"""Test Golden Hour filtering logic."""
import sys
sys.path.insert(0, ".")

from src.data_registry import DataRegistry as DR
from datetime import datetime, timedelta, timezone

# Load all closed positions
positions_data = DR.read_json(DR.POSITIONS_FUTURES)
all_closed = positions_data.get("closed_positions", []) if positions_data else []
print(f"Total closed positions: {len(all_closed)}")

# Filter by trading_window
gh_trades = [p for p in all_closed if p.get("trading_window") == "golden_hour"]
print(f"Golden Hour trades: {len(gh_trades)}")

# Filter to last 24 hours
cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
cutoff_ts = cutoff.timestamp()
print(f"Cutoff timestamp: {cutoff_ts} ({cutoff})")

recent_gh = []
for pos in gh_trades:
    closed_at = pos.get("closed_at", "")
    if not closed_at:
        continue
    try:
        if isinstance(closed_at, str):
            if "T" in closed_at:
                dt = datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
            else:
                dt = datetime.strptime(closed_at, "%Y-%m-%d %H:%M:%S")
            ts = dt.timestamp()
            if ts >= cutoff_ts:
                pnl = pos.get("pnl") or pos.get("net_pnl") or 0
                recent_gh.append({"symbol": pos.get("symbol"), "closed_at": closed_at, "pnl": pnl})
    except Exception as e:
        print(f"Error parsing {closed_at}: {e}")

print(f"\nGolden Hour trades in last 24h: {len(recent_gh)}")
if recent_gh:
    total_pnl = sum(p["pnl"] for p in recent_gh)
    print(f"Total P&L: ${total_pnl:.2f}")
    print("\nSample trades:")
    for p in recent_gh[:5]:
        print(f"  {p['symbol']}: ${p['pnl']:.2f} @ {p['closed_at']}")
else:
    print("\n⚠️ No Golden Hour trades in last 24 hours")
    if gh_trades:
        print(f"\nMost recent Golden Hour trade:")
        latest = sorted(gh_trades, key=lambda x: x.get("closed_at", ""), reverse=True)[0]
        print(f"  Symbol: {latest.get('symbol')}")
        print(f"  Closed at: {latest.get('closed_at')}")
        print(f"  P&L: {latest.get('pnl', latest.get('net_pnl', 'N/A'))}")

