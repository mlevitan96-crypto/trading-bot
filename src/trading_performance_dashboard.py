# trading_performance_dashboard.py
#
# Visual dashboard comparing Pre vs Post Phase 11.0 trading performance.
# Metrics: Win Rate (%), Realized P&L ($), Fees Paid ($), Net Portfolio Change ($)
# Displays grouped bar chart with side-by-side comparison.

import matplotlib.pyplot as plt
import numpy as np

def generate_performance_comparison():
    """Generate bar chart comparing Pre vs Post Phase 11.0 performance."""
    # Metrics
    categories = ['Win Rate (%)', 'Realized P&L ($)', 'Fees Paid ($)', 'Net Portfolio Change ($)']
    pre_phase = [0.5, -60.74, 123.25, 23.78]
    post_phase = [40.0, 50.00, 30.00, 80.00]

    x = np.arange(len(categories))
    width = 0.35

    plt.style.use('seaborn-v0_8')
    fig, ax = plt.subplots(figsize=(10, 6))

    bars1 = ax.bar(x - width/2, pre_phase, width, label='Pre-Phase 11.0', color='salmon')
    bars2 = ax.bar(x + width/2, post_phase, width, label='Post-Phase 11.0 (Expected)', color='mediumseagreen')

    # Labels and title
    ax.set_ylabel('Value')
    ax.set_title('Trading Performance Comparison: Pre vs Post Phase 11.0')
    ax.set_xticks(x)
    ax.set_xticklabels(categories)
    ax.legend()
    ax.grid(True, axis='y', linestyle='--', alpha=0.7)

    # Annotate bars
    for bars in [bars1, bars2]:
        for bar in bars:
            height = bar.get_height()
            ax.annotate(f'{height:.2f}',
                        xy=(bar.get_x() + bar.get_width() / 2, height),
                        xytext=(0, 5),
                        textcoords="offset points",
                        ha='center', va='bottom', fontsize=9)

    plt.tight_layout()
    
    # Save to file instead of showing
    import os
    os.makedirs('static', exist_ok=True)
    output_path = 'static/performance_comparison.png'
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    
    return output_path

if __name__ == "__main__":
    output = generate_performance_comparison()
    print(f"Performance comparison chart saved to: {output}")
