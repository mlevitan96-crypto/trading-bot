#!/usr/bin/env python3
"""
Display Export Data - Copy/Paste Friendly
==========================================
Outputs the analysis data in a format you can easily copy/paste.
"""

import json
import csv
import sys
from pathlib import Path

CSV_FILE = "/root/trading-bot-B/feature_store/signal_analysis_export.csv"
JSON_FILE = "/root/trading-bot-B/feature_store/signal_analysis_summary.json"

def display_csv_summary():
    """Display CSV data in readable format."""
    if not Path(CSV_FILE).exists():
        print(f"ERROR: {CSV_FILE} not found")
        print("Run: python3 export_signal_analysis.py first")
        return
    
    print("="*80)
    print("CSV DATA SUMMARY (First 20 trades)")
    print("="*80)
    print()
    
    with open(CSV_FILE, 'r') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        
        print(f"Total trades in CSV: {len(rows)}")
        print()
        print("Column headers:")
        print(", ".join(reader.fieldnames))
        print()
        print("First 20 trades:")
        print("-" * 80)
        
        for i, row in enumerate(rows[:20], 1):
            print(f"\nTrade {i}:")
            print(f"  Symbol: {row.get('symbol', 'N/A')}")
            print(f"  Strategy: {row.get('strategy', 'N/A')}")
            print(f"  Direction: {row.get('direction', 'N/A')}")
            print(f"  Entry: ${row.get('entry_price', '0')}")
            print(f"  Exit: ${row.get('exit_price', '0')}")
            print(f"  P&L: ${row.get('pnl_usd', '0')}")
            print(f"  Win: {row.get('win', 'N/A')}")
            print(f"  Regime: {row.get('regime', 'N/A')}")
            print(f"  OFI: {row.get('ofi', '0')}")
            print(f"  Ensemble: {row.get('ensemble', '0')}")
            print(f"  Liquidation Active: {row.get('liquidation_cascade_active', 'N/A')}")
            print(f"  Funding Rate: {row.get('funding_rate', '0')}")
            print(f"  Whale Flow: ${row.get('whale_flow_usd', '0')}")
            print(f"  Signal Matched: {row.get('signal_matched', 'N/A')}")
            print(f"  Has Components: {row.get('has_components', 'N/A')}")
    
    print()
    print("="*80)
    print("To get full CSV data, copy the file or use:")
    print(f"  cat {CSV_FILE}")
    print("="*80)

def display_json_summary():
    """Display JSON summary in readable format."""
    if not Path(JSON_FILE).exists():
        print(f"ERROR: {JSON_FILE} not found")
        return
    
    print()
    print("="*80)
    print("JSON SUMMARY")
    print("="*80)
    print()
    
    with open(JSON_FILE, 'r') as f:
        data = json.load(f)
    
    print(f"Generated: {data.get('generated_at', 'N/A')}")
    print(f"Total Trades: {data.get('total_trades', 0)}")
    print()
    
    print("Data Availability:")
    availability = data.get('data_availability', {})
    for key, value in availability.items():
        print(f"  {key}: {value}")
    print()
    
    print("Key Findings:")
    findings = data.get('key_findings', [])
    if findings:
        for finding in findings:
            print(f"  • {finding}")
    else:
        print("  No findings available")
    print()
    
    print("Hypothesis Results:")
    hypotheses = data.get('hypothesis_results', {})
    for hyp_name, hyp_data in hypotheses.items():
        status = hyp_data.get('status', 'unknown')
        print(f"  {hyp_name}: {status}")
        results = hyp_data.get('results', {})
        if results:
            for key, value in results.items():
                if isinstance(value, dict):
                    wr = value.get('win_rate', 0)
                    total = value.get('total', 0)
                    print(f"    {key}: {wr:.1%} win rate ({total} trades)")
    print()
    
    print("Data Quality Notes:")
    notes = data.get('data_quality_notes', {})
    for key, value in notes.items():
        print(f"  {key}: {value}")
    print()
    
    print("="*80)
    print("Full JSON (copy this):")
    print("="*80)
    print(json.dumps(data, indent=2))

def main():
    print("\n" + "="*80)
    print("EXPORT DATA DISPLAY - COPY/PASTE FRIENDLY")
    print("="*80)
    print()
    
    display_csv_summary()
    display_json_summary()
    
    print()
    print("="*80)
    print("TO COPY FULL CSV DATA:")
    print("="*80)
    print(f"Run: cat {CSV_FILE}")
    print("Then copy the output")
    print()

if __name__ == "__main__":
    main()
