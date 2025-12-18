# Kraken API Configuration Guide

## Current Bot Implementation

**Your bot uses REST API only** (no WebSocket implementation found):
- ✅ REST API is sufficient for your 60-second trading cycle
- ✅ Polling every 60 seconds is well within rate limits
- ✅ WebSocket would be optional optimization (not required)

---

## API Key Permissions: RECOMMENDED Settings

### ✅ Required Permissions (Enable These)

1. **Query Funds** ✅
   - Need: Check account balance
   - Used by: `get_balance()`, position sizing

2. **Query Open Orders & Trades** ✅
   - Need: Check current positions and orders
   - Used by: `get_positions()`, position tracking

3. **Create & Modify Orders** ✅
   - Need: Place and cancel orders
   - Used by: `place_order()`, `cancel_order()`

4. **Access Futures Data** ✅ (if available as separate option)
   - Need: Market data for futures trading
   - Used by: `get_mark_price()`, `fetch_ohlcv()`, `get_orderbook()`

### ❌ Do NOT Enable (Security)

- **Withdraw Funds** ❌ - Never needed for trading bot
- **Transfer Funds** ❌ - Not required for trading
- **Any withdrawal permissions** ❌ - Major security risk

---

## IP Address Restrictions: STRONGLY RECOMMENDED ⚠️

### Why IP Whitelisting?

**Critical Security Best Practice:**
- Limits API access to your server's IP address only
- Prevents unauthorized access even if API keys are compromised
- Kraken supports up to 15 IP addresses
- Reduces latency for direct access

### How to Configure

**For Kraken Futures:**
1. Go to https://futures.kraken.com
2. Click Settings (gear icon) → API Keys
3. Click "IP Whitelist"
4. Add your server's IP address(es):
   - **Droplet IP**: Your DigitalOcean droplet IP (if running on droplet)
   - **Home/Office IP**: Your local machine IP (if testing locally)
   - **VPN IP**: If using VPN (optional)

**Important Notes:**
- ⚠️ **If you enable IP whitelisting, API keys will ONLY work from whitelisted IPs**
- ⚠️ **If your IP changes, you'll need to update the whitelist**
- ✅ **Start with 1-2 IPs (server + local for testing)**
- ✅ **You can add more later if needed**

### Finding Your Server IP

**On DigitalOcean Droplet:**
```bash
curl ifconfig.me
# Or
hostname -I
```

**Add both IPv4 addresses if you have both.**

---

## WebSocket API: OPTIONAL (Not Currently Used)

### Current Status
- ❌ Bot does NOT use WebSocket
- ✅ Bot uses REST API polling (every 60 seconds)
- ✅ This is sufficient for your trading cycle

### Should You Enable WebSocket Support?

**Pros:**
- ✅ Real-time data (instant updates vs 60s polling)
- ✅ Lower API call volume (persistent connection)
- ✅ Better for high-frequency strategies (you're not high-frequency)

**Cons:**
- ❌ More complex implementation (connection management, reconnection logic)
- ❌ Not needed for 60-second cycle trading
- ❌ Additional code complexity to maintain

### Recommendation
**For Now: Skip WebSocket**
- Your bot runs on 60-second cycles
- REST API polling is sufficient
- Simpler = fewer bugs
- Can add WebSocket later if needed

**Future Consideration:**
- Only add WebSocket if you need:
  - Sub-second order execution
  - Real-time position updates
  - High-frequency trading strategies

---

## Security Checklist

### ✅ Must Do

1. **Enable IP Whitelisting** ⚠️
   - Add your droplet/server IP
   - Test with your local IP for development
   - Maximum security

2. **Minimal Permissions**
   - Only enable what's needed (Query, Orders, Futures Data)
   - Never enable withdrawal permissions

3. **Secure Key Storage**
   - Store keys in `.env` file (not in code)
   - Use environment variables in production
   - Never commit keys to git

4. **Key Naming**
   - Use descriptive names: "trading-bot-production", "trading-bot-testnet"
   - Makes it easy to identify and revoke if needed

### ✅ Recommended

5. **Testnet First**
   - Create separate API keys for testnet
   - Test all functionality on testnet before live
   - Use: `KRAKEN_FUTURES_TESTNET=true`

6. **Key Rotation**
   - Rotate API keys periodically (every 3-6 months)
   - Revoke old keys after rotation
   - Reduces long-term exposure risk

7. **Monitoring**
   - Check Kraken API key usage logs periodically
   - Look for unexpected activity
   - Alert on suspicious patterns

---

## Step-by-Step Setup

### Step 1: Create API Keys

1. Log into https://futures.kraken.com
2. Go to Settings → API Keys
3. Click "Generate API Key"
4. Name: `trading-bot-testnet` (or `trading-bot-production`)
5. **Enable Permissions:**
   - ✅ Query Funds
   - ✅ Query Open Orders & Trades
   - ✅ Create & Modify Orders
   - ✅ Access Futures Data (if available)
6. **Do NOT enable:**
   - ❌ Withdraw Funds
   - ❌ Transfer Funds
7. Click "Generate"

### Step 2: Get Your Server IP

**On your droplet:**
```bash
curl ifconfig.me
```

**Example output:** `159.65.168.230`

### Step 3: Configure IP Whitelist

1. In Kraken API settings, click "IP Whitelist"
2. Add your droplet IP: `159.65.168.230`
3. (Optional) Add your local IP for testing
4. Save

### Step 4: Save API Credentials

**Get from Kraken:**
- API Key (public)
- API Secret (private, base64-encoded)

**Add to `.env`:**
```bash
# Exchange Selection
EXCHANGE=kraken

# Kraken Futures API
KRAKEN_FUTURES_API_KEY=your_public_key_here
KRAKEN_FUTURES_API_SECRET=your_base64_secret_here
KRAKEN_FUTURES_TESTNET=true  # Start with testnet!
```

### Step 5: Test Connectivity

```bash
python src/kraken_futures_client.py
```

**Expected:**
- ✅ Symbol normalization works
- ✅ Public market data (mark prices, OHLCV)
- ✅ Authenticated queries (balance, positions)
- ❌ If IP whitelisting enabled and IP not whitelisted, you'll get auth errors

---

## IP Whitelisting: Important Considerations

### When to Enable
- ✅ **Production**: Always enable
- ✅ **Real money trading**: Must enable
- ⚠️ **Testing**: Can skip temporarily for flexibility

### When NOT to Enable (Temporary)
- ⚠️ **Development**: If your IP changes frequently
- ⚠️ **Testing from multiple locations**: Laptop, office, home
- ⚠️ **Dynamic IP addresses**: ISP assigns different IPs

### Recommendation
**Start WITHOUT IP whitelisting for testing:**
1. Create API keys without IP restrictions
2. Test all functionality
3. Once working, enable IP whitelist
4. Add your server IP
5. Remove test IPs before production

**For Production:**
- ✅ **Always enable IP whitelisting**
- ✅ Use only server IP(s)
- ✅ Remove any test/local IPs

---

## Rate Limits (Important)

Kraken Futures API limits:
- **Public REST**: ~20 requests/second
- **Private REST**: ~15 calls per 3 seconds (default tier)
- **Your bot**: ~1 request every 60 seconds = well under limits ✅

The rate limiter in `kraken_rate_limiter.py` uses:
- 60 req/min limit (conservative)
- 1.0s minimum delay between calls

This is safe and well within limits.

---

## Summary: What to Enable

### ✅ Enable in Kraken API Settings

**Permissions:**
- ✅ Query Funds
- ✅ Query Open Orders & Trades
- ✅ Create & Modify Orders
- ✅ Access Futures Data

**Security:**
- ✅ IP Whitelisting (add server IP after testing)
- ❌ WebSocket (not needed, skip for now)
- ❌ Withdrawal permissions (never)

### ❌ Skip (Not Needed)

- ❌ WebSocket support (not implemented, not needed)
- ❌ Withdrawal/Transfer permissions (security risk)
- ❌ All other optional features

---

## Troubleshooting

### Error: "Authentication failed"
- Check API key and secret are correct
- Verify API secret is base64-encoded (Kraken provides it this way)
- If IP whitelisting enabled, verify your IP is whitelisted

### Error: "IP not whitelisted"
- Add your current IP to whitelist
- Check if using VPN (need VPN IP instead)
- Verify you're accessing from correct server

### Error: "Permission denied"
- Check API key permissions are enabled
- Verify you enabled "Create & Modify Orders"
- Re-create API key if needed

---

## Next Steps

1. **Create API keys** with recommended permissions
2. **Test WITHOUT IP whitelisting** first
3. **Verify connectivity** using test script
4. **Enable IP whitelisting** after testing succeeds
5. **Switch to production** when ready
