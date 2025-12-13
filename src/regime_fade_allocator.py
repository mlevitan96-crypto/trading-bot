import json
import os


FADE_STATE = {
    "prev_caps": None,
    "target_caps": None,
    "steps": 5,
    "current_step": 0
}


def allocate_with_fade(new_caps, fade_steps=5):
    """
    Allocate capital with smooth regime transition fading.
    
    Instead of abrupt capital allocation changes during regime shifts,
    this interpolates between old and new allocations over N steps.
    
    Args:
        new_caps: Dict of {strategy: capital_allocation}
        fade_steps: Number of cycles to interpolate over (default 5)
    
    Returns:
        Dict of {strategy: faded_capital_allocation}
    """
    global FADE_STATE
    
    if FADE_STATE["prev_caps"] is None:
        FADE_STATE["prev_caps"] = new_caps.copy()
        FADE_STATE["target_caps"] = new_caps.copy()
        FADE_STATE["steps"] = fade_steps
        FADE_STATE["current_step"] = fade_steps
        return new_caps
    
    if new_caps != FADE_STATE["target_caps"]:
        FADE_STATE["prev_caps"] = get_current_faded_caps()
        FADE_STATE["target_caps"] = new_caps.copy()
        FADE_STATE["steps"] = fade_steps
        FADE_STATE["current_step"] = 0
        
        print(f"🔄 Regime allocation shift detected - fading over {fade_steps} cycles")
    
    t = FADE_STATE["current_step"] / max(1, FADE_STATE["steps"])
    
    all_strategies = set(FADE_STATE["prev_caps"].keys()) | set(FADE_STATE["target_caps"].keys())
    
    faded = {}
    for strategy in all_strategies:
        prev_val = FADE_STATE["prev_caps"].get(strategy, 0)
        target_val = FADE_STATE["target_caps"].get(strategy, 0)
        faded[strategy] = prev_val * (1 - t) + target_val * t
    
    FADE_STATE["current_step"] = min(FADE_STATE["current_step"] + 1, FADE_STATE["steps"])
    
    if FADE_STATE["current_step"] < FADE_STATE["steps"]:
        print(f"   Fade progress: {FADE_STATE['current_step']}/{FADE_STATE['steps']} " +
              f"({t*100:.0f}% toward target)")
    
    return faded


def get_current_faded_caps():
    """Get current faded capital allocations."""
    if FADE_STATE["prev_caps"] is None:
        return {}
    
    t = FADE_STATE["current_step"] / max(1, FADE_STATE["steps"])
    
    all_strategies = set(FADE_STATE["prev_caps"].keys()) | set(FADE_STATE["target_caps"].keys())
    
    faded = {}
    for strategy in all_strategies:
        prev_val = FADE_STATE["prev_caps"].get(strategy, 0)
        target_val = FADE_STATE["target_caps"].get(strategy, 0)
        faded[strategy] = prev_val * (1 - t) + target_val * t
    
    return faded


def reset_fade_state():
    """Reset fade state (useful for testing or manual intervention)."""
    global FADE_STATE
    FADE_STATE = {
        "prev_caps": None,
        "target_caps": None,
        "steps": 5,
        "current_step": 0
    }
    print("🔄 Regime fade state reset")


def get_fade_status():
    """Get current fade status for monitoring."""
    if FADE_STATE["prev_caps"] is None:
        return {"status": "uninitialized"}
    
    t = FADE_STATE["current_step"] / max(1, FADE_STATE["steps"])
    
    return {
        "status": "fading" if FADE_STATE["current_step"] < FADE_STATE["steps"] else "stable",
        "progress": t,
        "current_step": FADE_STATE["current_step"],
        "total_steps": FADE_STATE["steps"],
        "prev_caps": FADE_STATE["prev_caps"],
        "target_caps": FADE_STATE["target_caps"],
        "current_caps": get_current_faded_caps()
    }
