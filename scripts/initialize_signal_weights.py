#!/usr/bin/env python3
"""
Initialize Signal Weights File

Creates the signal weights file with default weights if it doesn't exist.
This enables signal weight learning to start working.
"""

import sys
import os
from pathlib import Path

# Add src to path
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent
sys.path.insert(0, str(project_root))

import json
from datetime import datetime, timezone

def initialize_signal_weights():
    """Initialize signal weights file with defaults if it doesn't exist."""
    
    weights_path = Path("feature_store/signal_weights.json")
    weights_gate_path = Path("feature_store/signal_weights_gate.json")
    
    # Default weights from weighted_signal_fusion
    default_entry_weights = {
        "ofi": 0.25,
        "ensemble": 0.20,
        "mtf_alignment": 0.15,
        "regime": 0.10,
        "market_intel": 0.10,
        "volume": 0.08,
        "momentum": 0.07,
        "session": 0.05
    }
    
    # Initialize main weights file
    if not weights_path.exists():
        weights_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "weights": default_entry_weights,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "metadata": {
                "initialized": True,
                "source": "default_weights",
                "note": "Initialized with default weights - learning will update these based on performance"
            }
        }
        with open(weights_path, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"✅ Initialized {weights_path}")
    else:
        print(f"ℹ️  {weights_path} already exists")
    
    # Initialize gate weights file (used by some systems)
    if not weights_gate_path.exists():
        weights_gate_path.parent.mkdir(parents=True, exist_ok=True)
        # Use predictive flow engine weights
        default_gate_weights = {
            'liquidation': 0.22,
            'funding': 0.16,
            'oi_velocity': 0.05,
            'whale_flow': 0.20,
            'ofi_momentum': 0.06,
            'fear_greed': 0.06,
            'hurst': 0.08,
            'lead_lag': 0.08,
            'volatility_skew': 0.05,
            'oi_divergence': 0.04
        }
        data = {
            "weights": default_gate_weights,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "metadata": {
                "initialized": True,
                "source": "default_weights",
                "note": "Initialized with default weights - learning will update these based on performance"
            }
        }
        with open(weights_gate_path, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"✅ Initialized {weights_gate_path}")
    else:
        print(f"ℹ️  {weights_gate_path} already exists")
    
    print("\n✅ Signal weights files initialized - learning can now track and update weights")

if __name__ == "__main__":
    initialize_signal_weights()

