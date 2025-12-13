#!/usr/bin/env python3
"""
MONEY-HUNTING ANALYSIS - Paper Mode = Learn Everything
Analyzes all patterns from a PROFIT perspective, not a defensive one.
"""

import json
from collections import defaultdict
from src.data_registry import DataRegistry as DR


def load_jsonl(path):
    records = []
    try:
        with open(path, 'r') as f:
            for line in f:
                try:
                    records.append(json.loads(line.strip()))
                except:
                    continue
    except:
        pass
    return records


def run_money_analysis():
    print('='*70)
    print('💰 MONEY-HUNTING ANALYSIS - PAPER MODE = LEARN EVERYTHING')
    print('='*70)

    enriched = load_jsonl(DR.ENRICHED_DECISIONS)
    print(f'\n📊 Analyzing {len(enriched)} trades with PROFIT LENS...\n')

    patterns = defaultdict(lambda: {
        'trades': 0, 'wins': 0, 'pnl': 0, 
        'winner_pnls': [], 'loser_pnls': [],
        'ofi_sum': 0
    })

    for rec in enriched:
        ctx = rec.get('signal_ctx', {})
        outcome = rec.get('outcome', {})
        
        symbol = rec.get('symbol', '')
        side = ctx.get('side', '')
        pnl = outcome.get('pnl_usd', 0)
        ofi = abs(ctx.get('ofi', 0))
        
        if not symbol or not side:
            continue
        
        key = f'{symbol}_{side}'
        patterns[key]['trades'] += 1
        patterns[key]['pnl'] += pnl
        patterns[key]['ofi_sum'] += ofi
        
        if pnl > 0:
            patterns[key]['wins'] += 1
            patterns[key]['winner_pnls'].append(pnl)
        else:
            patterns[key]['loser_pnls'].append(pnl)

    print('📈 PATTERNS RANKED BY MONEY-MAKING POTENTIAL:')
    print('-'*70)

    results = []
    for key, stats in patterns.items():
        if stats['trades'] < 3:
            continue
        
        wr = stats['wins'] / stats['trades'] * 100
        avg_winner = sum(stats['winner_pnls']) / len(stats['winner_pnls']) if stats['winner_pnls'] else 0
        avg_loser = sum(stats['loser_pnls']) / len(stats['loser_pnls']) if stats['loser_pnls'] else 0
        rr = abs(avg_winner / avg_loser) if avg_loser != 0 else 0
        
        ev = (wr/100) * avg_winner - ((100-wr)/100) * abs(avg_loser)
        
        breakeven_wr = (1 / (1 + rr)) * 100 if rr > 0 else 50
        wr_gap = wr - breakeven_wr
        
        score = 0
        reason = ''
        
        if stats['pnl'] > 0:
            score = 100 + stats['pnl']
            reason = '💰 PROFITABLE'
        elif ev > 0:
            score = 80 + ev * 10
            reason = '📈 POSITIVE EV'
        elif rr >= 1.0:
            score = 60 + rr * 10
            reason = f'⚖️ GOOD R/R (need {breakeven_wr:.0f}% WR)'
        elif wr >= 20:
            score = 40 + wr
            reason = '📊 DECENT WR'
        else:
            score = wr_gap + 20
            reason = '🔬 NEEDS DATA'
        
        results.append({
            'pattern': key,
            'score': score,
            'reason': reason,
            'trades': stats['trades'],
            'wr': wr,
            'pnl': stats['pnl'],
            'avg_winner': avg_winner,
            'avg_loser': avg_loser,
            'rr': rr,
            'ev': ev,
            'breakeven_wr': breakeven_wr,
            'wr_gap': wr_gap
        })

    results.sort(key=lambda x: x['score'], reverse=True)

    header = f"{'Pattern':<20} {'Score':>6} {'WR%':>6} {'P&L':>8} {'R/R':>5} {'EV':>7} {'BE_WR':>6} {'Gap':>6} Verdict"
    print(header)
    print('-'*100)

    for r in results:
        gap_str = f"+{r['wr_gap']:.0f}%" if r['wr_gap'] > 0 else f"{r['wr_gap']:.0f}%"
        print(f"{r['pattern']:<20} {r['score']:>6.0f} {r['wr']:>5.1f}% ${r['pnl']:>7.2f} {r['rr']:>5.2f} ${r['ev']:>6.2f} {r['breakeven_wr']:>5.0f}% {gap_str:>6} {r['reason']}")

    print()
    print('='*70)
    print('🎯 KEY INSIGHTS FOR MONEY-MAKING:')
    print('='*70)

    profitable = [r for r in results if r['pnl'] > 0]
    positive_ev = [r for r in results if r['ev'] > 0 and r['pnl'] <= 0]
    good_rr = [r for r in results if r['rr'] >= 1.0 and r['pnl'] <= 0 and r['ev'] <= 0]

    print(f'\n✅ ALREADY PROFITABLE ({len(profitable)}):')
    for r in profitable[:5]:
        print(f"   {r['pattern']}: ${r['pnl']:.2f} profit")

    print(f'\n📈 MATHEMATICALLY SHOULD PROFIT ({len(positive_ev)}):')
    for r in positive_ev[:5]:
        print(f"   {r['pattern']}: EV=${r['ev']:.2f}/trade, R/R={r['rr']:.2f}")

    print(f'\n⚖️ GOOD R/R - JUST NEED BETTER ENTRIES ({len(good_rr)}):')
    for r in good_rr[:5]:
        print(f"   {r['pattern']}: R/R={r['rr']:.2f}, needs {r['breakeven_wr']:.0f}% WR (currently {r['wr']:.0f}%)")

    close_to_profit = [r for r in results if r['wr_gap'] > -10 and r['pnl'] < 0]
    print(f'\n🎯 CLOSE TO BREAKEVEN (within 10% WR):')
    for r in sorted(close_to_profit, key=lambda x: x['wr_gap'], reverse=True)[:5]:
        gap_str = f"+{r['wr_gap']:.0f}%" if r['wr_gap'] > 0 else f"{r['wr_gap']:.0f}%"
        print(f"   {r['pattern']}: {gap_str} from breakeven (WR={r['wr']:.0f}%, BE={r['breakeven_wr']:.0f}%)")

    total_potential = sum(r['ev'] * 10 for r in results if r['ev'] > 0)
    print(f'\n💵 TOTAL POTENTIAL (if we trade +EV patterns 10x more): ${total_potential:.2f}')
    
    return results


if __name__ == "__main__":
    run_money_analysis()
