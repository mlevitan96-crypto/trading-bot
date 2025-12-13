"""
Visualization tools for offline analysis of trading bot performance.
Generates static images for regime shifts, strategy weights, and missed opportunities.
"""
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend for server environment
import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
import numpy as np
from pathlib import Path
import json
from datetime import datetime

REGIME_WEIGHTS_FILE = "logs/regime_weights.json"
MISSED_OPP_FILE = "logs/missed_opportunities.json"
OUTPUT_DIR = "logs/visualizations"

def ensure_output_dir():
    """Create visualization output directory."""
    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

def render_regime_shifts_timeline(output_file="regime_shifts.png"):
    """
    Generate a timeline visualization of regime shifts and strategy weights.
    
    Args:
        output_file: Output filename (saved to logs/visualizations/)
    
    Returns:
        Path to generated image or None if no data
    """
    ensure_output_dir()
    
    if not Path(REGIME_WEIGHTS_FILE).exists():
        print("⚠️ No regime weights data available for visualization")
        return None
    
    with open(REGIME_WEIGHTS_FILE, 'r') as f:
        data = json.load(f)
    
    regime_log = data.get("regime_log", [])
    
    if not regime_log:
        print("⚠️ No regime shifts logged yet")
        return None
    
    df = pd.DataFrame(regime_log)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    
    fig, ax = plt.subplots(figsize=(14, 6))
    
    # Plot regime changes as vertical lines
    for i, row in df.iterrows():
        weights_str = ", ".join([f"{k}: {v:.1%}" for k, v in row["weights"].items()])
        label = f"{row['regime']}\n{weights_str}"
        
        ax.axvline(row["timestamp"], linestyle="--", alpha=0.6, color='gray')
        ax.text(row["timestamp"], 0.5 + (i % 3) * 0.15, label, 
                rotation=45, verticalalignment="bottom", fontsize=9,
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    
    ax.set_title("📈 Regime Shifts & Strategy Weight Evolution", fontsize=14, fontweight='bold')
    ax.set_xlabel("Time", fontsize=12)
    ax.set_ylim(0, 1)
    ax.set_yticks([])
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    
    output_path = Path(OUTPUT_DIR) / output_file
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    
    print(f"✅ Regime shifts visualization saved to {output_path}")
    return str(output_path)

def render_missed_opportunity_heatmap(output_file="missed_opportunities_heatmap.png"):
    """
    Generate a heatmap showing which filters block the most profitable trades.
    
    Args:
        output_file: Output filename (saved to logs/visualizations/)
    
    Returns:
        Path to generated image or None if no data
    """
    ensure_output_dir()
    
    if not Path(MISSED_OPP_FILE).exists():
        print("⚠️ No missed opportunity data available for visualization")
        return None
    
    with open(MISSED_OPP_FILE, 'r') as f:
        data = json.load(f)
    
    heatmap_data = data.get("heatmap", {})
    
    if not heatmap_data:
        print("⚠️ No missed opportunities logged yet")
        return None
    
    # Convert to DataFrame
    heatmap_df = pd.DataFrame.from_dict(heatmap_data, orient="index").fillna(0)
    
    # Create heatmap
    plt.figure(figsize=(12, max(6, len(heatmap_df) * 0.5)))
    sns.heatmap(heatmap_df, annot=True, fmt=".0f", cmap="YlOrRd", 
                linewidths=0.5, cbar_kws={'label': 'Count'})
    plt.title("🔥 Missed Opportunity Heatmap\n(Profitable trades blocked by filters)", 
              fontsize=14, fontweight='bold')
    plt.xlabel("Blocked Filter", fontsize=12)
    plt.ylabel("Symbol + Regime", fontsize=12)
    plt.tight_layout()
    
    output_path = Path(OUTPUT_DIR) / output_file
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    
    print(f"✅ Missed opportunity heatmap saved to {output_path}")
    return str(output_path)

def render_strategy_performance_chart(output_file="strategy_performance.png"):
    """
    Generate a bar chart showing average ROI per strategy by regime.
    
    Args:
        output_file: Output filename (saved to logs/visualizations/)
    
    Returns:
        Path to generated image or None if no data
    """
    ensure_output_dir()
    
    strategy_memory_file = "logs/strategy_memory.json"
    if not Path(strategy_memory_file).exists():
        print("⚠️ No strategy performance data available for visualization")
        return None
    
    with open(strategy_memory_file, 'r') as f:
        data = json.load(f)
    
    performance = data.get("performance", {})
    
    if not performance:
        print("⚠️ No strategy performance logged yet")
        return None
    
    # Extract data
    strategies = []
    avg_rois = []
    executed_counts = []
    
    for key, perf in performance.items():
        strategies.append(key)
        avg_roi = np.mean(perf["roi_history"]) if perf["roi_history"] else 0
        avg_rois.append(avg_roi * 100)  # Convert to percentage
        executed_counts.append(perf["executed_count"])
    
    # Create chart
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))
    
    # ROI chart
    colors = ['green' if roi > 0 else 'red' for roi in avg_rois]
    ax1.barh(strategies, avg_rois, color=colors, alpha=0.7)
    ax1.set_xlabel("Average ROI (%)", fontsize=12)
    ax1.set_title("📊 Strategy Performance by Regime", fontsize=14, fontweight='bold')
    ax1.axvline(0, color='black', linewidth=0.8)
    ax1.grid(True, alpha=0.3, axis='x')
    
    # Execution count chart
    ax2.barh(strategies, executed_counts, color='steelblue', alpha=0.7)
    ax2.set_xlabel("Execution Count", fontsize=12)
    ax2.set_title("📈 Strategy Execution Frequency", fontsize=14, fontweight='bold')
    ax2.grid(True, alpha=0.3, axis='x')
    
    plt.tight_layout()
    
    output_path = Path(OUTPUT_DIR) / output_file
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    
    print(f"✅ Strategy performance chart saved to {output_path}")
    return str(output_path)

def generate_all_visualizations():
    """
    Generate all available visualizations.
    
    Returns:
        Dict with paths to generated images
    """
    print("\n" + "="*60)
    print("📊 Generating Visualizations")
    print("="*60)
    
    results = {
        "regime_shifts": render_regime_shifts_timeline(),
        "missed_opportunities": render_missed_opportunity_heatmap(),
        "strategy_performance": render_strategy_performance_chart()
    }
    
    generated = {k: v for k, v in results.items() if v is not None}
    
    print(f"\n✅ Generated {len(generated)}/{len(results)} visualizations")
    return generated
