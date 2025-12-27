# Deployment Instructions for Autonomous Brain Integration

## Overview
This document provides instructions for deploying and verifying the autonomous brain integration on the droplet.

## Step 1: Pull Latest Code

```bash
cd /root/trading-bot-current
git pull origin main
```

## Step 2: Install Dependencies

```bash
source venv/bin/activate
pip install -r requirements.txt
```

Verify required packages:
- numpy
- hmmlearn
- optuna
- schedule

## Step 3: Run Code Verification

```bash
python verify_integration_code.py
```

This verifies all integration patterns exist in the code without requiring imports.

## Step 4: Verify Integration (if dependencies available)

```bash
python audit_autonomous_brain_integration.py
```

This runs a full audit with imports (requires all dependencies installed).

## Step 5: Check Service Status

```bash
systemctl status trading-bot
```

## Step 6: Restart Service (if needed)

```bash
systemctl restart trading-bot
systemctl status trading-bot
```

## Step 7: Check Logs

```bash
journalctl -u trading-bot -f --lines=100
```

Look for:
- ✅ [SHADOW] Shadow portfolio comparison started
- ✅ [POLICY-TUNER] Policy optimizer started
- ✅ [DRIFT] Feature drift detection started
- ✅ [ADAPTIVE-SIGNAL] Regime classifier integration
- ✅ [AUTONOMOUS-BRAIN] integration markers

## Step 8: Verify File Structure

Ensure these files exist:
- `src/regime_classifier.py`
- `src/shadow_execution_engine.py`
- `src/policy_tuner.py`
- `src/feature_drift_detector.py`
- `src/adaptive_signal_optimizer.py`

## Step 9: Verify Data Files (will be created at runtime)

- `logs/shadow_results.jsonl`
- `feature_store/regime_classifier_state.json`
- `feature_store/drift_detector_state.json`

## Integration Checklist

- [ ] Code pulled from git
- [ ] Dependencies installed
- [ ] Code verification passed
- [ ] Service running
- [ ] Logs show autonomous brain components starting
- [ ] No import errors in logs
- [ ] All schedulers started successfully

## Troubleshooting

### Import Errors
If you see `ModuleNotFoundError`, install missing packages:
```bash
pip install <package-name>
```

### Service Won't Start
Check logs for errors:
```bash
journalctl -u trading-bot --no-pager | tail -50
```

### Integration Not Working
Run verification script to identify missing patterns:
```bash
python verify_integration_code.py
```

