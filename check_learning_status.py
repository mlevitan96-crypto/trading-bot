#!/usr/bin/env python3
"""Check what learning systems are doing about losing trends"""

import json
import os
import sys
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, '.')

# Check recent trade performance
print("=" * 70)
print("RECENT TRADE PERFORMANCE ANALYSIS")
print("=" * 70)
print()

positions_file = 'logs/positions_futures.json'
if os.path.exists(positions_file):
    with open(positions_file, 'r') as f:
        data = json.load(f)
    closed = data.get('closed_positions', [])
    
    if closed:
        # Last 50 trades
        recent = closed[-50:]
        total_pnl = sum(float(p.get('pnl', p.get('net_pnl', 0)) or 0) for p in recent)
        wins = sum(1 for p in recent if float(p.get('pnl', p.get('net_pnl', 0)) or 0) > 0)
        losses = len(recent) - wins
        
        print(f"Last 50 trades:")
        print(f"  Total P&L: ${total_pnl:.2f}")
        print(f"  Win Rate: {wins}/{len(recent)} ({wins/len(recent)*100:.1f}%)")
        print(f"  Average P&L: ${total_pnl/len(recent):.2f}")
        print()
        
        # Last 100 trades
        recent_100 = closed[-100:]
        total_pnl_100 = sum(float(p.get('pnl', p.get('net_pnl', 0)) or 0) for p in recent_100)
        wins_100 = sum(1 for p in recent_100 if float(p.get('pnl', p.get('net_pnl', 0)) or 0) > 0)
        
        print(f"Last 100 trades:")
        print(f"  Total P&L: ${total_pnl_100:.2f}")
        print(f"  Win Rate: {wins_100}/{len(recent_100)} ({wins_100/len(recent_100)*100:.1f}%)")
        print()

# Check learning state
print("=" * 70)
print("LEARNING SYSTEMS STATUS")
print("=" * 70)
print()

learning_state = 'feature_store/learning_state.json'
if os.path.exists(learning_state):
    with open(learning_state, 'r') as f:
        state = json.load(f)
    print(f"Learning State File: {learning_state}")
    print(f"  Last cycle time: {state.get('last_cycle_time', 'unknown')}")
    print(f"  Total cycles: {state.get('total_cycles', 0)}")
    print(f"  Pending adjustments: {len(state.get('pending_adjustments', []))}")
    if state.get('pending_adjustments'):
        print(f"  Adjustments:")
        for adj in state.get('pending_adjustments', [])[:5]:
            print(f"    - {adj.get('type', 'unknown')}: {adj.get('description', 'no description')}")
    print()
else:
    print(f"❌ Learning state file not found: {learning_state}")
    print()

# Check counterfactual intelligence
print("=" * 70)
print("COUNTERFACTUAL INTELLIGENCE")
print("=" * 70)
print()

cf_log = 'logs/learning_updates.jsonl'
if os.path.exists(cf_log):
    with open(cf_log, 'r') as f:
        lines = f.readlines()
    
    # Find counterfactual entries
    counterfactual_entries = []
    for line in lines[-500:]:  # Check last 500 lines
        try:
            entry = json.loads(line.strip())
            if 'counterfactual' in str(entry).lower() or entry.get('update_type') == 'counterfactual_cycle':
                counterfactual_entries.append(entry)
        except:
            continue
    
    print(f"Counterfactual entries found: {len(counterfactual_entries)}")
    if counterfactual_entries:
        latest = counterfactual_entries[-1]
        print(f"  Last run timestamp: {latest.get('ts', 'unknown')}")
        print(f"  Blocked signals analyzed: {latest.get('blocked_count', 0)}")
        if 'aggregate_by_reason' in latest:
            print(f"  Block reasons breakdown:")
            for reason, data in list(latest.get('aggregate_by_reason', {}).items())[:5]:
                print(f"    - {reason}: {data.get('count', 0)} blocked, net P&L: ${data.get('net_pnl_sum', 0):.2f}")
    else:
        print("  ⚠️  No counterfactual analysis entries found in recent logs")
    print()
else:
    print(f"❌ Counterfactual log not found: {cf_log}")
    print()

# Check blocked signals
print("=" * 70)
print("BLOCKED SIGNALS ANALYSIS")
print("=" * 70)
print()

signals_log = 'logs/signals.jsonl'
if os.path.exists(signals_log):
    with open(signals_log, 'r') as f:
        lines = f.readlines()
    
    recent_signals = []
    for line in lines[-200:]:  # Last 200 signals
        try:
            sig = json.loads(line.strip())
            recent_signals.append(sig)
        except:
            continue
    
    blocked = [s for s in recent_signals if s.get('status') == 'blocked' or s.get('disposition') == 'BLOCKED']
    
    print(f"Recent signals analyzed: {len(recent_signals)}")
    print(f"Blocked signals: {len(blocked)} ({len(blocked)/len(recent_signals)*100:.1f}%)")
    
    if blocked:
        reasons = defaultdict(int)
        for s in blocked:
            reason = s.get('block_reason', s.get('reason', s.get('disposition', 'unknown')))
            reasons[reason] += 1
        
        print(f"  Top block reasons:")
        for reason, count in sorted(reasons.items(), key=lambda x: x[1], reverse=True)[:10]:
            print(f"    - {reason}: {count}")
    print()
else:
    print(f"❌ Signals log not found: {signals_log}")
    print()

# Check learning updates file for recent activity
print("=" * 70)
print("RECENT LEARNING ACTIVITY")
print("=" * 70)
print()

if os.path.exists(cf_log):
    with open(cf_log, 'r') as f:
        lines = f.readlines()
    
    # Get last 50 entries
    recent_entries = []
    for line in lines[-50:]:
        try:
            entry = json.loads(line.strip())
            recent_entries.append(entry)
        except:
            continue
    
    # Group by update type
    by_type = defaultdict(list)
    for entry in recent_entries:
        update_type = entry.get('update_type', 'unknown')
        by_type[update_type].append(entry)
    
    print(f"Recent learning updates (last 50 entries):")
    for update_type, entries in sorted(by_type.items(), key=lambda x: len(x[1]), reverse=True):
        latest = entries[-1]
        ts = latest.get('ts', latest.get('timestamp', 'unknown'))
        print(f"  {update_type}: {len(entries)} entries, last: {ts}")
    print()

# Check signal weights (if learning is adjusting them)
print("=" * 70)
print("SIGNAL WEIGHTS (Learning Adjustments)")
print("=" * 70)
print()

signal_weights = 'feature_store/signal_weights.json'
if os.path.exists(signal_weights):
    with open(signal_weights, 'r') as f:
        weights = json.load(f)
    print("Current signal weights:")
    if isinstance(weights, dict):
        for signal, weight_data in list(weights.items())[:10]:
            if isinstance(weight_data, dict):
                weight = weight_data.get('weight', weight_data.get('value', weight_data))
                print(f"  {signal}: {weight}")
            else:
                print(f"  {signal}: {weight_data}")
    print()
else:
    print(f"❌ Signal weights file not found: {signal_weights}")
    print()

# Summary
print("=" * 70)
print("SUMMARY")
print("=" * 70)
print()

if total_pnl < 0:
    print(f"⚠️  LOSING TREND: Last 50 trades show ${abs(total_pnl):.2f} loss")
    print(f"   Win rate: {wins/len(recent)*100:.1f}%")
    print()
    print("Learning systems should be:")
    print("  1. Analyzing these losses")
    print("  2. Adjusting signal weights")
    print("  3. Analyzing blocked signals (counterfactual)")
    print("  4. Proposing threshold adjustments")
    print()
    print("Check above sections to see if learning is active.")
else:
    print(f"✅ Recent trades are profitable: ${total_pnl:.2f}")

