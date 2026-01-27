# Deploying to Render - Polymarket Whale Tracker

## Quick Start (Option 1: Background Worker - $7/month)

### 1. Prepare Your Repository

```bash
# Initialize git if not already done
cd /Users/christabb/Downloads/files
git init
git add .
git commit -m "Initial commit - Polymarket Whale Tracker"

# Create GitHub repo and push
gh repo create polymarket-whale-tracker --private --push
```

### 2. Connect to Render

1. Go to [render.com](https://render.com) and sign up/login
2. Click **New +** → **Background Worker**
3. Connect your GitHub repo
4. Configure:
   - **Name**: `polymarket-whale-tracker`
   - **Region**: Oregon (or closest to you)
   - **Branch**: `main`
   - **Runtime**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python small_capital_system.py`
   - **Plan**: Starter ($7/month)

### 3. Add Environment Variables

In the Render dashboard, add these environment variables:

| Variable | Description |
|----------|-------------|
| `POLYGON_RPC_URL` | Your Polygon RPC (Alchemy/Infura) |
| `POLYMARKET_API_KEY` | From Polymarket CLOB |
| `POLYMARKET_API_SECRET` | From Polymarket CLOB |
| `POLYMARKET_API_PASSPHRASE` | From Polymarket CLOB |
| `PRIVATE_KEY` | Your wallet private key |
| `WALLET_ADDRESS` | Your wallet address |
| `AUTO_COPY_ENABLED` | `false` for dry run, `true` for live |
| `ANTHROPIC_API_KEY` | Optional - Claude AI validation |

### 4. Deploy

Click **Create Background Worker** and Render will:
- Build your application
- Start the worker
- Automatically restart on failures
- Keep it running 24/7

## Monitoring

### View Logs
```bash
# Install Render CLI
brew install render

# View live logs
render logs --tail polymarket-whale-tracker
```

Or view logs in the Render dashboard under your service.

### Health Checks

The system writes `scan_progress.json` with current status. Check the logs for:
- `Connected to Polygon: Block X` - Successful startup
- `Found X specialists` - Scan complete
- `Monitoring for trades...` - Active monitoring

## Cost Breakdown

| Service | Plan | Cost |
|---------|------|------|
| Background Worker | Starter | $7/month |
| **Total** | | **$7/month** |

## Upgrading to Live Trading

1. In Render dashboard, go to Environment
2. Change `AUTO_COPY_ENABLED` to `true`
3. Render will auto-restart with live trading enabled

## Troubleshooting

### Worker keeps restarting
- Check logs for errors
- Verify all environment variables are set
- Ensure RPC URL is valid and has credits

### Missing trades
- Increase `BLOCKS_TO_SCAN` in config
- Check Polygon RPC rate limits

### High latency
- Use a faster RPC provider
- Consider Oregon region for US markets
