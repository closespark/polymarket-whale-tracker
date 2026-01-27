# Deploying to Render - Polymarket Whale Tracker v2

## Quick Deploy with Persistent Disk (~$8/month)

### 1. Add Persistent Disk (Required for Database)

Go to your Render dashboard:
1. Open https://dashboard.render.com/worker/srv-d5s3oqa4d50c73d2g6k0
2. Click **Disks** in the left sidebar
3. Click **Add Disk**
4. Configure:
   - **Name**: `whale-tracker-data`
   - **Mount Path**: `/data`
   - **Size**: 5 GB (~$1/month)
5. Click **Save**

### 2. Add Environment Variables

Go to **Environment** tab and add/update:

| Variable | Value | Description |
|----------|-------|-------------|
| `DB_PATH` | `/data/trades.db` | Database on persistent disk |
| `POLYGON_RPC_URL` | Your URL | Alchemy/Infura Polygon RPC |
| `AUTO_COPY_ENABLED` | `false` | Dry run mode (change to `true` for live) |
| `ANTHROPIC_API_KEY` | (optional) | For Claude AI validation |
| `POLYMARKET_API_KEY` | (for live) | From Polymarket CLOB |
| `POLYMARKET_API_SECRET` | (for live) | From Polymarket CLOB |
| `POLYMARKET_API_PASSPHRASE` | (for live) | From Polymarket CLOB |
| `PRIVATE_KEY` | (for live) | Your wallet private key |
| `WALLET_ADDRESS` | (for live) | Your wallet address |

### 3. Deploy Latest Code

1. Go to **Deploys** tab
2. Click **Manual Deploy** → **Deploy latest commit**

Or via API:
```bash
curl -X POST "https://api.render.com/v1/services/srv-d5s3oqa4d50c73d2g6k0/deploys" \
  -H "Authorization: Bearer rnd_3xPVMXfvXLY4UbR68mMkNKarVVS9" \
  -H "Content-Type: application/json" \
  -d '{"clearCache": false}'
```

### 4. Upload Pre-Scanned Database (Saves ~30 min)

**Option A: Add SSH Key to Render**
1. Go to Account Settings → SSH Keys
2. Add your public key:
```bash
cat ~/.ssh/id_ed25519.pub
```
3. Copy and paste into Render

**Option B: Upload via SCP**
```bash
# From your local machine (after adding SSH key)
scp trades.db srv-d5s3oqa4d50c73d2g6k0@ssh.oregon.render.com:/data/trades.db
```

**Option C: Let Render Scan Fresh**
- Skip upload - system will do deep scan on first run
- Takes ~30 minutes initially
- After that, only incremental updates

---

## What's New in v2

- **Kelly Criterion sizing**: Mathematically optimal position sizes
- **WebSocket monitoring**: 2-5 second detection (vs 60 seconds)
- **Risk management**: Trailing stops, exposure limits
- **Whale intelligence**: Correlation, MM detection, specialization
- **Multi-timeframe**: 15min, hourly, 4hr, daily tiers
- **SQLite storage**: 94% fewer RPC calls

---

## Cost Breakdown

| Service | Plan | Cost |
|---------|------|------|
| Background Worker | Starter | $7/month |
| Persistent Disk | 5 GB | $1/month |
| **Total** | | **$8/month** |

---

## Monitoring

### View Logs
Check the Render dashboard → Logs tab

Expected output:
```
💰 SMALL CAPITAL SYSTEM v2
   Starting capital: $100
   Kelly Criterion sizing: ENABLED
   WebSocket monitoring: ENABLED
   Risk management: ENABLED
   Whale intelligence: ENABLED
   Multi-timeframe: ENABLED

⚡ ULTRA-FAST DISCOVERY v2 (Optimized)
   Scan interval: Every 60s (new blocks only)
   Pool refresh: Every 15min (from database)
   Storage: SQLite (/data/trades.db)

📊 Multi-Timeframe Strategy initialized
   Tiers: ['15min', 'hourly', '4hour', 'daily']
```

---

## Troubleshooting

**Issue: "No such file: /data/trades.db"**
- Normal on first run if DB not uploaded
- System will create new one and run deep scan (~30 min)

**Issue: WebSocket connection fails**
- Falls back to polling mode automatically
- Ensure POLYGON_RPC_URL supports WebSockets

**Issue: High memory during initial scan**
- Deep scan loads events into memory
- Will reduce after initial scan completes
- Starter plan (512MB) is sufficient

---

## Upgrading to Live Trading

1. Ensure you have:
   - Polymarket API credentials
   - Wallet with USDC on Polygon
   - Private key configured

2. In Render dashboard:
   - Change `AUTO_COPY_ENABLED` to `true`
   - Service auto-restarts with live trading

⚠️ **Start with small amounts** - The system is in dry run mode by default for safety.
