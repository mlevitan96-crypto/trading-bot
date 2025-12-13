#!/usr/bin/env python3
"""
Trading Bot Analysis Tools

Utility script to generate visualizations and run simulations.
Run this manually when you want to analyze bot performance.

Usage:
    python analysis_tools.py --visualize    # Generate charts
    python analysis_tools.py --simulate     # Run sample simulation
    python analysis_tools.py --all          # Do both
"""
import argparse
from src.visualization_tools import generate_all_visualizations
from src.simulation_engine import create_sample_simulation

def main():
    parser = argparse.ArgumentParser(description='Trading Bot Analysis Tools')
    parser.add_argument('--visualize', action='store_true', 
                       help='Generate all visualizations')
    parser.add_argument('--simulate', action='store_true',
                       help='Run sample simulation')
    parser.add_argument('--all', action='store_true',
                       help='Generate visualizations and run simulation')
    
    args = parser.parse_args()
    
    # Default to --all if no args provided
    if not any([args.visualize, args.simulate, args.all]):
        args.all = True
    
    if args.visualize or args.all:
        print("\n" + "="*60)
        print("📊 Generating Visualizations")
        print("="*60)
        results = generate_all_visualizations()
        print(f"\n✅ Generated {len(results)} visualization(s)")
        for name, path in results.items():
            print(f"   📈 {name}: {path}")
    
    if args.simulate or args.all:
        print("\n" + "="*60)
        print("🔬 Running Sample Simulation")
        print("="*60)
        results = create_sample_simulation()
        print(f"\n📊 Simulation Results:")
        print(f"   Total Trades: {results['total_trades']}")
        print(f"   Average ROI: {results['average_roi_pct']:.4f}%")

if __name__ == "__main__":
    main()
