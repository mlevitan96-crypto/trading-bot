#!/usr/bin/env python3
import sys
sys.path.insert(0, ".")

from src.data_registry import DataRegistry as DR
from datetime import datetime, timedelta, timezone

pos = DR.read_json(DR.POSITIONS_FUTURES)
closed = pos.get("closed_positions", []) if pos else []
print(f"Total closed positions: {len(closed)}")

# Check last 24 hours
cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
cutoff_ts = cutoff.timestamp()
print(f"\nCutoff: {cutoff} (timestamp: {cutoff_ts})")
print(f"Current UTC: {datetime.now(timezone.utc)}")

recent_24h = []
for p in closed[-100:]:  # Check last 100
    ca = p.get("closed_at", "")
    if not ca:
        continue
    try:
        if isinstance(ca, str):
            if "T" in ca:
                dt = datetime.fromisoformat(ca.replace("Z", "+00:00"))
            else:
                dt = datetime.strptime(ca, "%Y-%m-%d %H:%M:%S")
            ts = dt.timestamp()
            if ts >= cutoff_ts:
                pnl = float(p.get("pnl", p.get("net_pnl", 0)) or 0)
                recent_24h.append({"symbol": p.get("symbol"), "closed_at": ca, "pnl": pnl})
    except Exception as e:
        print(f"Error parsing {ca}: {e}")

print(f"\nTrades in last 24 hours: {len(recent_24h)}")
if recent_24h:
    total_pnl = sum(p["pnl"] for p in recent_24h)
    print(f"Total P&L: ${total_pnl:.2f}")
    print("\nSample trades:")
    for p in recent_24h[:5]:
        print(f"  {p['symbol']}: ${p['pnl']:.2f} @ {p['closed_at']}")
else:
    print("\nMost recent trade:")
    if closed:
        latest = closed[-1]
        print(f"  Symbol: {latest.get('symbol')}")
        print(f"  Closed at: {latest.get('closed_at')}")
        if latest.get('closed_at'):
            ca = latest.get('closed_at')
            try:
                if isinstance(ca, str) and "T" in ca:
                    dt = datetime.fromisoformat(ca.replace("Z", "+00:00"))
                    ts = dt.timestamp()
                    print(f"  Timestamp: {ts}")
                    print(f"  Hours ago: {(datetime.now(timezone.utc).timestamp() - ts) / 3600:.2f}")
            except:
                pass

