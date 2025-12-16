# Quick Start - Droplet Deployment
## 3 Steps to Deploy Clean Architecture

---

## ✅ What You Need

- SSH access to droplet
- Git access to repository
- Dashboard password: `Echelonlev2007!`

---

## 🚀 3-Step Deployment

### Step 1: Pull Latest Code

```bash
ssh root@YOUR_DROPLET_IP
cd /root/trading-bot-current
git pull origin main
```

### Step 2: Restart Bot

```bash
systemctl restart tradingbot
```

### Step 3: Verify It's Working

```bash
# Check logs for new components
tail -f logs/bot_out.log | grep -E "SHADOW|STATE-MACHINE"

# Should see:
# 🔮 [SHADOW] Shadow execution engine started
# ✅ [STATE-MACHINE] State machine started
```

---

## 📊 Access Dashboard

1. **Open browser:** `http://YOUR_DROPLET_IP:8501`
2. **Login:** Password `Echelonlev2007!`
3. **Click "Analytics" tab**
4. **See real-time insights!**

---

## ✅ That's It!

**No structural changes needed!** Everything works with existing deployment.

**New components start automatically:**
- ✅ SignalBus
- ✅ StateMachine
- ✅ ShadowExecutionEngine
- ✅ DecisionTracker
- ✅ PipelineMonitor

**New dashboard features:**
- ✅ Analytics tab
- ✅ Pipeline health
- ✅ Guard effectiveness
- ✅ Blocked opportunities

---

## 🔍 Verify Everything

### Check Signal Bus
```bash
tail -f logs/signal_bus.jsonl
# Should see new entries as signals are generated
```

### Check Shadow Engine
```bash
ls -lh logs/shadow_trade_outcomes.jsonl
# File should exist and grow over time
```

### Check Dashboard
- Open Analytics tab
- Should see pipeline health metrics
- Should see blocked opportunity cost (after a few hours)

---

## ⚠️ Troubleshooting

### No data in Analytics?
**Wait a few hours** - Shadow engine needs time to track outcomes.

### Dashboard not loading?
```bash
systemctl status tradingbot
# Check if service is running
```

### Errors in logs?
```bash
tail -f logs/bot_out.log | grep -i error
# Check for any errors
```

---

## 📚 Full Documentation

See `DROPLET_DEPLOYMENT_GUIDE.md` for complete details.

---

## 🎉 Ready!

**Everything is complete and ready for full trading, learning, and updating!**

The "big wheel" is spinning! 🎡

