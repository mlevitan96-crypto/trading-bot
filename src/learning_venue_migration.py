"""
Learning Venue Migration - Manages venue-aware learning state.

When switching from Blofin to Kraken (or any venue change):
1. Tags all learning files with current venue
2. Resets or heavily decays old venue learnings
3. Creates conservative initial values for new venue
4. Clamps learning adjustments during initial learning period (7-14 days)
5. Ensures bot learns from new venue data, not old venue data

Key Learning Files:
- signal_weights_gate.json / signal_weights.json
- hold_time_policy.json
- fee_gate_learning.json
- daily_learning_rules.json
- edge_sizer_calibration.json
- strategic_advisor_state.json
- correlation_throttle_policy.json
- direction_rules.json
- rotation_rules.json
"""

import os
import json
import time
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List
from datetime import datetime, timedelta
from copy import deepcopy

from src.infrastructure.path_registry import PathRegistry


# Learning files that need venue tagging
LEARNING_FILES = {
    "signal_weights": PathRegistry.FEATURE_STORE_DIR / "signal_weights_gate.json",
    "hold_time_policy": PathRegistry.FEATURE_STORE_DIR / "hold_time_policy.json",
    "fee_gate_learning": PathRegistry.FEATURE_STORE_DIR / "fee_gate_learning.json",
    "daily_learning_rules": PathRegistry.FEATURE_STORE_DIR / "daily_learning_rules.json",
    "edge_sizer_calibration": PathRegistry.FEATURE_STORE_DIR / "edge_sizer_calibration.json",
    "strategic_advisor_state": PathRegistry.FEATURE_STORE_DIR / "strategic_advisor_state.json",
    "correlation_throttle_policy": PathRegistry.FEATURE_STORE_DIR / "correlation_throttle_policy.json",
    "direction_rules": PathRegistry.FEATURE_STORE_DIR / "direction_rules.json",
    "rotation_rules": PathRegistry.FEATURE_STORE_DIR / "rotation_rules.json",
}

# Venue migration state file
VENUE_MIGRATION_STATE = PathRegistry.FEATURE_STORE_DIR / "venue_migration_state.json"

# Learning period settings (first 7-14 days on new venue)
INITIAL_LEARNING_DAYS = 14
MAX_WEIGHT_CHANGE_PCT = 10.0  # Max ±10% weight change during initial period
INITIAL_LEVERAGE_CAP = 2.0  # Lower leverage cap initially (vs normal 5-10x)
INITIAL_POSITION_SIZE_MULT = 0.5  # 50% of normal position size initially


class VenueMigrationManager:
    """
    Manages venue-aware learning state migration and tagging.
    """
    
    def __init__(self):
        self.current_venue = os.getenv("EXCHANGE", "blofin").lower()
        self.migration_state_file = VENUE_MIGRATION_STATE
        self.migration_state_file.parent.mkdir(parents=True, exist_ok=True)
        
    def load_migration_state(self) -> Dict[str, Any]:
        """Load venue migration state."""
        if self.migration_state_file.exists():
            try:
                with open(self.migration_state_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"⚠️ [VENUE-MIGRATION] Failed to load migration state: {e}")
                return {}
        return {}
    
    def save_migration_state(self, state: Dict[str, Any]):
        """Save venue migration state."""
        try:
            with open(self.migration_state_file, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            print(f"⚠️ [VENUE-MIGRATION] Failed to save migration state: {e}")
    
    def detect_venue_change(self) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Detect if venue has changed.
        
        Returns:
            (has_changed, old_venue, new_venue)
        """
        state = self.load_migration_state()
        last_venue = state.get("last_venue", "blofin").lower()
        
        if last_venue != self.current_venue:
            return True, last_venue, self.current_venue
        
        return False, None, None
    
    def tag_learning_file(self, file_path: Path, venue: str) -> bool:
        """
        Tag a learning file with venue metadata.
        
        Returns:
            True if file was updated, False otherwise
        """
        if not file_path.exists():
            return False
        
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
            
            # Add venue metadata
            if "_venue_metadata" not in data:
                data["_venue_metadata"] = {}
            
            data["_venue_metadata"]["current_venue"] = venue
            data["_venue_metadata"]["venue_set_date"] = datetime.utcnow().isoformat() + "Z"
            data["_venue_metadata"]["last_updated"] = datetime.utcnow().isoformat() + "Z"
            
            # Backup original
            backup_path = file_path.with_suffix('.json.backup')
            if not backup_path.exists():
                with open(backup_path, 'w') as f:
                    json.dump(data, f, indent=2)
            
            # Write updated
            with open(file_path, 'w') as f:
                json.dump(data, f, indent=2)
            
            return True
            
        except Exception as e:
            print(f"⚠️ [VENUE-MIGRATION] Failed to tag {file_path.name}: {e}")
            return False
    
    def reset_or_decay_learning(self, file_path: Path, venue: str, decay_factor: float = 0.1) -> bool:
        """
        Reset or decay learning values when switching venues.
        
        Args:
            file_path: Path to learning file
            venue: New venue name
            decay_factor: How much to keep (0.1 = keep 10%, reset 90%)
        
        Returns:
            True if file was modified, False otherwise
        """
        if not file_path.exists():
            return False
        
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
            
            # Check if already tagged for this venue
            venue_meta = data.get("_venue_metadata", {})
            if venue_meta.get("current_venue") == venue:
                # Already migrated for this venue
                return False
            
            # Backup old venue data
            backup_path = file_path.with_suffix(f'.json.{venue_meta.get("current_venue", "unknown")}.backup')
            with open(backup_path, 'w') as f:
                json.dump(data, f, indent=2)
            
            # Reset or decay values
            modified = False
            
            # Handle different file structures
            if "signal_weights" in str(file_path) or "weights" in str(file_path):
                # Signal weights: decay to neutral (1.0)
                if isinstance(data, dict):
                    for key, value in data.items():
                        if key.startswith("_") or key == "_venue_metadata":
                            continue
                        if isinstance(value, (int, float)):
                            # Decay to 1.0 (neutral)
                            new_value = 1.0 + (value - 1.0) * decay_factor
                            data[key] = new_value
                            modified = True
                        elif isinstance(value, dict):
                            # Recursively handle nested weights
                            for subkey, subvalue in value.items():
                                if isinstance(subvalue, (int, float)):
                                    new_value = 1.0 + (subvalue - 1.0) * decay_factor
                                    value[subkey] = new_value
                                    modified = True
            
            elif "hold_time" in str(file_path) or "policy" in str(file_path):
                # Policy files: reset to conservative defaults
                if isinstance(data, dict):
                    # Keep structure, reset aggressive values to conservative
                    for key, value in data.items():
                        if key.startswith("_") or key == "_venue_metadata":
                            continue
                        if isinstance(value, dict) and "min" in str(key).lower():
                            # Increase minimums (more conservative)
                            if isinstance(value, dict):
                                for subkey in value:
                                    if isinstance(value[subkey], (int, float)) and value[subkey] > 0:
                                        value[subkey] = value[subkey] * (1.0 + (1.0 - decay_factor))
                                        modified = True
            
            elif "fee_gate" in str(file_path) or "calibration" in str(file_path):
                # Calibration files: reset to neutral/moderate values
                if isinstance(data, dict):
                    for key, value in data.items():
                        if key.startswith("_") or key == "_venue_metadata":
                            continue
                        if isinstance(value, (int, float)):
                            # Move toward neutral (1.0) or moderate defaults
                            if abs(value) > 1.0:
                                data[key] = 1.0 + (value - 1.0) * decay_factor
                                modified = True
            
            # Tag with new venue
            if "_venue_metadata" not in data:
                data["_venue_metadata"] = {}
            data["_venue_metadata"]["current_venue"] = venue
            data["_venue_metadata"]["venue_set_date"] = datetime.utcnow().isoformat() + "Z"
            data["_venue_metadata"]["migrated_from"] = venue_meta.get("current_venue", "unknown")
            data["_venue_metadata"]["decay_factor"] = decay_factor
            
            if modified:
                data["_venue_metadata"]["last_updated"] = datetime.utcnow().isoformat() + "Z"
                with open(file_path, 'w') as f:
                    json.dump(data, f, indent=2)
            
            return modified
            
        except Exception as e:
            print(f"⚠️ [VENUE-MIGRATION] Failed to migrate {file_path.name}: {e}")
            return False
    
    def is_initial_learning_period(self) -> bool:
        """
        Check if we're in the initial learning period for current venue.
        
        Returns:
            True if within first INITIAL_LEARNING_DAYS on current venue
        """
        state = self.load_migration_state()
        venue_start_date = state.get("venue_start_dates", {}).get(self.current_venue)
        
        if not venue_start_date:
            return True  # New venue, assume initial period
        
        try:
            start = datetime.fromisoformat(venue_start_date.replace("Z", "+00:00"))
            days_since_start = (datetime.utcnow() - start.replace(tzinfo=None)).days
            return days_since_start < INITIAL_LEARNING_DAYS
        except:
            return True  # On error, assume initial period
    
    def get_learning_clamp_multiplier(self) -> float:
        """
        Get multiplier to clamp learning adjustments during initial period.
        
        Returns:
            Multiplier (1.0 = no clamping, 0.1 = 10% of normal adjustment)
        """
        if not self.is_initial_learning_period():
            return 1.0  # No clamping after initial period
        
        state = self.load_migration_state()
        venue_start_date = state.get("venue_start_dates", {}).get(self.current_venue)
        
        if not venue_start_date:
            return 0.1  # Very conservative for brand new venue
        
        try:
            start = datetime.fromisoformat(venue_start_date.replace("Z", "+00:00"))
            days_since_start = (datetime.utcnow() - start.replace(tzinfo=None)).days
            
            # Gradually increase from 0.1 to 1.0 over INITIAL_LEARNING_DAYS
            progress = min(days_since_start / INITIAL_LEARNING_DAYS, 1.0)
            return 0.1 + (0.9 * progress)  # Linear ramp from 0.1 to 1.0
        except:
            return 0.1
    
    def migrate_venue(self, decay_factor: float = 0.1) -> Dict[str, Any]:
        """
        Perform venue migration: tag files, reset/decay old learnings.
        
        Args:
            decay_factor: How much of old learning to keep (0.1 = keep 10%)
        
        Returns:
            Migration results dict
        """
        results = {
            "venue": self.current_venue,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "files_tagged": [],
            "files_migrated": [],
            "files_skipped": [],
            "errors": []
        }
        
        # Detect venue change
        has_changed, old_venue, new_venue = self.detect_venue_change()
        
        if not has_changed:
            # Just tag files with current venue (if not already tagged)
            for name, path in LEARNING_FILES.items():
                if path.exists():
                    if self.tag_learning_file(path, self.current_venue):
                        results["files_tagged"].append(name)
                    else:
                        results["files_skipped"].append(name)
            return results
        
        print(f"\n🔄 [VENUE-MIGRATION] Detected venue change: {old_venue} → {new_venue}")
        print(f"   Resetting/decaying old learnings (keeping {decay_factor*100:.0f}%)...\n")
        
        # Migrate each learning file
        for name, path in LEARNING_FILES.items():
            if not path.exists():
                results["files_skipped"].append(f"{name} (not found)")
                continue
            
            try:
                if self.reset_or_decay_learning(path, new_venue, decay_factor):
                    results["files_migrated"].append(name)
                    print(f"   ✅ Migrated: {name}")
                else:
                    results["files_skipped"].append(name)
            except Exception as e:
                error_msg = f"{name}: {str(e)}"
                results["errors"].append(error_msg)
                print(f"   ❌ Error migrating {name}: {e}")
        
        # Update migration state
        state = self.load_migration_state()
        if "venue_start_dates" not in state:
            state["venue_start_dates"] = {}
        state["venue_start_dates"][new_venue] = datetime.utcnow().isoformat() + "Z"
        state["last_venue"] = new_venue
        state["last_migration"] = results["timestamp"]
        state["migration_results"] = results
        self.save_migration_state(state)
        
        print(f"\n✅ [VENUE-MIGRATION] Migration complete: {len(results['files_migrated'])} files migrated")
        print(f"   Initial learning period: {INITIAL_LEARNING_DAYS} days")
        print(f"   Max weight change: ±{MAX_WEIGHT_CHANGE_PCT}% during initial period")
        print(f"   Initial leverage cap: {INITIAL_LEVERAGE_CAP}x")
        print(f"   Initial position size: {INITIAL_POSITION_SIZE_MULT*100:.0f}% of normal\n")
        
        return results
    
    def get_venue_metadata(self, file_path: Path) -> Optional[Dict[str, Any]]:
        """Get venue metadata from a learning file."""
        if not file_path.exists():
            return None
        
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
            return data.get("_venue_metadata")
        except:
            return None


def migrate_venue_learning(decay_factor: float = 0.1) -> Dict[str, Any]:
    """
    Main entry point for venue migration.
    
    Call this on bot startup to ensure learning files are venue-aware.
    """
    manager = VenueMigrationManager()
    return manager.migrate_venue(decay_factor=decay_factor)


if __name__ == "__main__":
    # Test venue migration
    results = migrate_venue_learning()
    print("\n📊 Migration Results:")
    print(f"   Files tagged: {len(results['files_tagged'])}")
    print(f"   Files migrated: {len(results['files_migrated'])}")
    print(f"   Files skipped: {len(results['files_skipped'])}")
    if results['errors']:
        print(f"   Errors: {len(results['errors'])}")
        for error in results['errors']:
            print(f"      - {error}")
