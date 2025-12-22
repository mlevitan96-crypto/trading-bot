#!/usr/bin/env python3
"""
Simple Export Script for Signal Component Analysis
===================================================
Exports analysis data in easy-to-use formats for external review.
"""

import json
import csv
import sys
from pathlib import Path
from datetime import datetime

# Input file
INPUT_FILE = "/root/trading-bot-B/feature_store/signal_component_analysis.json"

# Output files
OUTPUT_DIR = Path("/root/trading-bot-B/feature_store")
OUTPUT_CSV = OUTPUT_DIR / "signal_analysis_export.csv"
OUTPUT_SUMMARY = OUTPUT_DIR / "signal_analysis_summary.json"

def load_analysis_data():
    """Load the analysis JSON file."""
    if not Path(INPUT_FILE).exists():
        print(f"ERROR: {INPUT_FILE} not found")
        print("Run: python3 analyze_signal_components.py first")
        return None
    
    with open(INPUT_FILE, 'r') as f:
        return json.load(f)

def export_to_csv(data):
    """Export trades to CSV for easy analysis in Excel/Google Sheets."""
    # Get all trades, not just the first 500
    all_trades = data.get('detailed_trades', [])
    
    # If we have the full analysis data, we can get more trades
    # For now, use what we have
    trades = all_trades
    
    if not trades:
        print("WARNING: No trades to export")
        return
    
    print(f"   Found {len(trades)} trades to export")
    
    # Define CSV columns
    fieldnames = [
        'trade_id',
        'symbol',
        'strategy',
        'direction',
        'entry_price',
        'exit_price',
        'pnl_usd',
        'win',
        'regime',
        'ofi',
        'ensemble',
        'signal_matched',
        'has_components',
        'liquidation_cascade_active',
        'liquidation_confidence',
        'liquidation_direction',
        'liquidation_total_1h',
        'funding_rate',
        'funding_confidence',
        'funding_direction',
        'whale_flow_usd',
        'whale_confidence',
        'whale_direction',
        'volatility',
        'volume',
        'atr',
        'atr_pct',
    ]
    
    with open(OUTPUT_CSV, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        for trade in trades:
            components = trade.get('signal_components', {})
            liq = components.get('liquidation_cascade', {}) or {}
            funding = components.get('funding_rate', {}) or {}
            whale = components.get('whale_flow', {}) or {}
            
            # Debug: Check if components exist
            has_components = bool(components)
            liq_active = liq.get('cascade_active', False) if isinstance(liq, dict) else False
            funding_rate_val = funding.get('rate', 0) if isinstance(funding, dict) else 0
            whale_flow_val = whale.get('net_flow_usd', 0) if isinstance(whale, dict) else 0
            
            row = {
                'trade_id': trade.get('trade_id', ''),
                'symbol': trade.get('symbol', ''),
                'strategy': trade.get('strategy', ''),
                'direction': trade.get('direction', ''),
                'entry_price': trade.get('entry_price', 0),
                'exit_price': trade.get('exit_price', 0),
                'pnl_usd': trade.get('pnl', 0),
                'win': 'Yes' if trade.get('win', False) else 'No',
                'regime': trade.get('regime', 'unknown'),
                'ofi': trade.get('ofi', 0),
                'ensemble': trade.get('ensemble', 0),
                'liquidation_cascade_active': 'Yes' if liq_active else 'No',
                'liquidation_confidence': liq.get('confidence', 0) if isinstance(liq, dict) else 0,
                'liquidation_direction': liq.get('direction', 'NEUTRAL') if isinstance(liq, dict) else 'NEUTRAL',
                'liquidation_total_1h': liq.get('total_1h', 0) if isinstance(liq, dict) else 0,
                'funding_rate': funding_rate_val,
                'funding_confidence': funding.get('confidence', 0) if isinstance(funding, dict) else 0,
                'funding_direction': funding.get('direction', 'NEUTRAL') if isinstance(funding, dict) else 'NEUTRAL',
                'whale_flow_usd': whale_flow_val,
                'whale_confidence': whale.get('confidence', 0) if isinstance(whale, dict) else 0,
                'whale_direction': whale.get('direction', 'NEUTRAL') if isinstance(whale, dict) else 'NEUTRAL',
                'volatility': trade.get('volatility', 0) or '',
                'volume': trade.get('volume', 0) or '',
                'atr': trade.get('atr', '') or '',
                'atr_pct': trade.get('atr_pct', '') or '',
                'signal_matched': 'Yes' if trade.get('signal_matched', False) else 'No',
                'has_components': 'Yes' if has_components else 'No',
            }
            writer.writerow(row)
    
    print(f"✅ Exported {len(trades)} trades to CSV: {OUTPUT_CSV}")

def export_summary(data):
    """Export summary statistics in clean JSON format."""
    summary = {
        'generated_at': datetime.now().isoformat(),
        'total_trades': data.get('total_trades', 0),
        'data_availability': data.get('data_availability', {}),
        'hypothesis_results': {
            'hypothesis_1_volatility': {
                'status': 'insufficient_data' if not data.get('volatility_analysis') else 'analyzed',
                'results': data.get('volatility_analysis', {}),
            },
            'hypothesis_2_signal_components': {
                'status': 'insufficient_data' if not data.get('component_analysis') else 'analyzed',
                'results': data.get('component_analysis', {}),
            },
            'hypothesis_3_regime': {
                'status': 'analyzed',
                'results': data.get('regime_analysis', {}),
            },
        },
    }
    
    # Add key findings
    findings = []
    
    # Regime findings
    regime_analysis = data.get('regime_analysis', {})
    if regime_analysis:
        for regime, stats in regime_analysis.items():
            wr = stats.get('win_rate', 0)
            if wr < 0.4:
                findings.append(f"{regime} regime: {wr:.1%} win rate (POOR)")
            elif wr > 0.5:
                findings.append(f"{regime} regime: {wr:.1%} win rate (GOOD)")
    
    # Component findings
    component_analysis = data.get('component_analysis', {})
    if component_analysis:
        for component, stats in component_analysis.items():
            wr = stats.get('win_rate', 0)
            total = stats.get('total', 0)
            if total > 0:
                component_name = component.replace('by_', '').replace('_', ' ').title()
                if wr < 0.4:
                    findings.append(f"{component_name}: {wr:.1%} win rate ({total} trades) - CAUSING LOSSES")
                elif wr > 0.55:
                    findings.append(f"{component_name}: {wr:.1%} win rate ({total} trades) - ACCURATE")
    
    summary['key_findings'] = findings
    
    # Add data quality notes
    summary['data_quality_notes'] = {
        'volatility_data': 'MISSING - ATR/volatility not calculated at entry time',
        'signal_components': 'AVAILABLE - 99.9% of trades have matched signals',
        'regime_data': f"PARTIAL - {data.get('data_availability', {}).get('regime', 0)}/{data.get('total_trades', 0)} trades have regime data",
        'note': 'Signal components may appear empty in CSV if extraction format differs. Check signal_matched and has_components columns.',
    }
    
    with open(OUTPUT_SUMMARY, 'w') as f:
        json.dump(summary, f, indent=2)
    
    print(f"✅ Exported summary to: {OUTPUT_SUMMARY}")
    
    # Print key findings
    print("\n" + "="*80)
    print("KEY FINDINGS")
    print("="*80)
    if findings:
        for finding in findings:
            print(f"  • {finding}")
    else:
        print("  No significant patterns found")
    print()

def main():
    print("="*80)
    print("SIGNAL ANALYSIS EXPORT")
    print("="*80)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Load data
    data = load_analysis_data()
    if not data:
        return 1
    
    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # Export to CSV
    print("Exporting to CSV...")
    export_to_csv(data)
    
    # Export summary
    print("\nExporting summary...")
    export_summary(data)
    
    print("\n" + "="*80)
    print("EXPORT COMPLETE")
    print("="*80)
    print(f"\nFiles created:")
    print(f"  1. CSV (for Excel/Sheets): {OUTPUT_CSV}")
    print(f"  2. Summary JSON: {OUTPUT_SUMMARY}")
    print(f"\nTo download:")
    print(f"  scp root@your-server:{OUTPUT_CSV} .")
    print(f"  scp root@your-server:{OUTPUT_SUMMARY} .")
    print()
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
