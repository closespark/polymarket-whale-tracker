# Polymarket Whale Tracker

A real-time whale trade detection and copy-trading system for Polymarket prediction markets on Polygon.

## Overview

This system monitors whale traders on Polymarket's CTF Exchange, analyzes their trading patterns by timeframe specialty, and evaluates whether to copy their trades using a multi-tier confidence system.

### Key Features

- **Real-time WebSocket monitoring** - 2-5 second trade detection latency
- **Multi-timeframe tier system** - Categorizes whales by specialty (15min, hourly, 4hour, daily)
- **SQLite-backed analysis** - 94% reduction in RPC calls vs polling
- **Kelly Criterion position sizing** - Mathematically optimal bet sizing
- **Claude AI validation** - Optional AI-powered trade analysis
- **Whale intelligence** - Correlation detection, market maker filtering, consensus tracking
- **Embedded web dashboard** - Real-time monitoring at port 8080
- **Automatic whale management** - Hourly promotion/pruning based on performance
- **Position persistence** - Trades survive restarts via SQLite

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        small_capital_system.py                       │
│                         (Main Orchestrator)                          │
└─────────────────────────────────────────────────────────────────────┘
                                    │
         ┌──────────────────────────┼──────────────────────────┐
         ▼                          ▼                          ▼
┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
│ ultra_fast_     │      │ websocket_      │      │ multi_timeframe │
│ discovery.py    │      │ monitor.py      │      │ _strategy.py    │
│                 │      │                 │      │                 │
│ • Incremental   │      │ • WebSocket     │      │ • Tier system   │
│   block scans   │      │   subscriptions │      │ • Threshold     │
│ • SQLite store  │      │ • Real-time     │      │   calculation   │
│ • Pool refresh  │      │   detection     │      │ • Specialty     │
└────────┬────────┘      └────────┬────────┘      │   matching      │
         │                        │               └────────┬────────┘
         ▼                        ▼                        │
┌─────────────────────────────────────────────────────────┐│
│                    trade_database.py                     ││
│                                                          ││
│  • SQLite storage (trades.db)                            ││
│  • Trader analysis by timeframe                          │◄┘
│  • Market metadata caching (Gamma API)                   │
│  • Tier assignment & whale management                    │
│  • Dry run position tracking                             │
└──────────────────────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────┐
│                    embedded_dashboard.py                  │
│                                                          │
│  • Real-time web dashboard (port 8080)                   │
│  • Capital/ROI tracking (24h committed capital)          │
│  • Whale observations analytics                          │
│  • Pending/resolved position display                     │
└──────────────────────────────────────────────────────────┘
```

## System Flow

### 1. Startup & Tier Population

```python
_populate_multi_timeframe_tiers() → multi_tf_strategy.load_from_database(db)
```

- Fetches market metadata from Polymarket Gamma API
- Runs SQL analysis to find specialists by timeframe
- Populates tiers (currently: 15 from 15min + 10 from daily = 25 whales)

### 2. WebSocket Monitoring

```python
run_monitoring() → _get_all_tier_addresses() → HybridMonitor(whale_addresses)
```

- Gets addresses **only from populated tiers** (database is single source of truth)
- Subscribes to `OrderFilled` events on CTF Exchange (`0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E`)
- Triggers callback when monitored whale trades

### 3. Trade Evaluation

When a whale trades, the system runs:

1. **Base confidence** from `score_trade()`
2. **Claude AI validation** (optional) - can adjust up/down
3. **Whale Intelligence** - correlation, market maker detection, consensus
4. **Multi-Timeframe Strategy** - tier-based threshold calculation

### 4. Threshold Calculation

| Tier | Base Threshold | Outside Specialty (+6%) |
|------|----------------|-------------------------|
| 15min | 88% | 94% |
| hourly | 90% | 96% |
| 4hour | 92% | 98% |
| daily | 93% | 99% |

**Example**: A daily specialist (93% base) trading a 15-minute market (outside specialty) requires **99% confidence** to copy.

### 5. Whale Management Loop

The system automatically manages its whale roster every hour:

1. **Promote top performers** - Whales from observations with 80%+ win rate and 5+ trades get promoted to active monitoring
2. **Prune underperformers** - Active whales that drop below 80% win rate are removed
3. **Reload tiers** - Memory is synced with database after changes

## Update Intervals

| Component | Interval | Purpose |
|-----------|----------|---------|
| Whale observation resolution | 60s | Track whale trade outcomes |
| Tier promotion check | 30m | Check for whales ready to promote |
| Whale management (prune/promote) | 60m | Hourly roster cleanup |
| Position resolution | 30s | Check if pending positions resolved |
| Dashboard refresh | 5s | Client-side auto-refresh |

## Installation

### Prerequisites

- Python 3.9+
- Polygon RPC endpoint (Alchemy recommended for WebSocket support)

### Setup

```bash
# Clone and install dependencies
pip install web3 websockets python-dotenv requests pandas anthropic aiohttp

# Create .env file
cp .env.example .env
```

### Environment Variables

```env
# Required
POLYGON_RPC_URL=https://polygon-mainnet.g.alchemy.com/v2/YOUR_KEY

# Optional - for live trading
AUTO_COPY_ENABLED=false
POLYMARKET_API_KEY=your_key
POLYMARKET_SECRET=your_secret
POLYMARKET_PASSPHRASE=your_passphrase
PRIVATE_KEY=your_private_key

# Optional - for AI validation
ANTHROPIC_API_KEY=your_anthropic_key

# Whale discovery criteria
MIN_WHALE_PROFIT=5000
MIN_WHALE_WIN_RATE=0.60

# Database path (default: trades.db)
DB_PATH=trades.db

# Clear positions on restart (default: false)
CLEAR_POSITIONS=false

# Maintenance mode (pauses system for DB uploads)
MAINTENANCE_MODE=false
```

## Usage

### Run the main system

```bash
python small_capital_system.py
```

### Run discovery only

```bash
python ultra_fast_discovery.py
```

### Run WebSocket monitor standalone

```bash
python websocket_monitor.py
```

### Access the dashboard

The embedded dashboard runs on port 8080. For remote servers:

```bash
# SSH tunnel from Render or similar
ssh -L 8080:localhost:8080 srv-xxx@ssh.render.com
# Then open http://localhost:8080 in browser
```

## Key Files

| File | Purpose |
|------|---------|
| `small_capital_system.py` | Main orchestrator - runs all components |
| `ultra_fast_discovery.py` | Incremental blockchain scanning, SQLite storage |
| `websocket_monitor.py` | Real-time WebSocket event subscriptions |
| `multi_timeframe_strategy.py` | Tier system, threshold calculation |
| `trade_database.py` | SQLite storage, timeframe analysis, Gamma API, whale management |
| `embedded_dashboard.py` | Real-time web dashboard (port 8080) |
| `whale_intelligence.py` | Correlation detection, market maker filtering |
| `kelly_sizing.py` | Kelly Criterion position sizing |
| `risk_manager.py` | Drawdown limits, exposure management |
| `claude_validator.py` | Claude AI trade validation (optional) |
| `market_lifecycle.py` | Market resolution tracking via Gamma API |
| `order_executor.py` | Live order execution (when AUTO_COPY_ENABLED=true) |
| `position_manager.py` | Live position tracking |
| `market_resolver.py` | Market outcome detection |
| `config.py` | Configuration and contract ABIs |

## Database Schema

The system uses SQLite (`trades.db`) with these key tables:

### Core Tables

| Table | Purpose |
|-------|---------|
| `token_timeframes` | Token ID → timeframe mapping (from Gamma API) |
| `whale_timeframe_stats` | Active whale roster (who we monitor) |
| `whale_incremental_stats` | Whale observations (running totals from resolution) |
| `whale_pending_trades` | Pending whale trades awaiting resolution |
| `dry_run_positions` | Our simulated trades (persists across restarts) |
| `scan_metadata` | System state tracking |

### Data Isolation

The system keeps data properly segregated:

- **`dry_run_positions`** - OUR actual trades only (used for Capital/ROI display)
- **`whale_incremental_stats`** - Whale observations (trades we watched but didn't copy)
- **`whale_pending_trades`** - Pending whale trades for quality tracking

This ensures Capital/ROI on the dashboard only reflects trades we actually took, not retroactive whale performance.

## Tier System Details

### How Whales Are Assigned to Tiers

1. **Market metadata fetch** - Polymarket Gamma API provides market questions
2. **Timeframe inference** - Keywords like "15 min", "hourly", "daily" determine category
3. **SQL analysis** - Aggregates win rate by trader by timeframe
4. **Tier assignment** - Top performers in each timeframe join respective tier

### Tier Requirements

| Tier | Min Trades | Min Win Rate | Max Whales |
|------|------------|--------------|------------|
| 15min | 15 | 70% | 15 |
| hourly | 12 | 68% | 15 |
| 4hour | 8 | 65% | 10 |
| daily | 8 | 65% | 10 |

### Automatic Whale Management

Every hour, the system:

1. **Promotes** whales from observations with 80%+ win rate and 5+ resolved trades
2. **Prunes** active whales that have dropped below 80% win rate

This creates a self-maintaining roster of high-performing whales.

## Risk Management

- **Max per trade**: 15% of capital
- **Max per whale**: 25% of capital
- **Max daily exposure**: 60% of capital
- **Stop-loss**: 30% drawdown triggers system halt
- **Kelly fraction**: 0.25 (quarter Kelly for safety)

## Dashboard Features

The embedded dashboard at port 8080 provides:

- **Capital/ROI** - Uses 24-hour committed capital for dry run mode (more meaningful than static $100)
- **Win/Loss tracking** - Real-time trade outcomes
- **Tier breakdown** - Whales by specialty timeframe
- **Pending positions** - Trades awaiting resolution
- **Whale observations** - Performance of all observed whales

### API Endpoints

| Endpoint | Description |
|----------|-------------|
| `/` | HTML dashboard |
| `/api/stats` | Live trading stats (Capital, ROI, win rate) |
| `/api/whales` | All monitored whales with tier info |
| `/api/tiers` | Tier breakdown and stats |
| `/api/trades` | Recent trade history |
| `/api/pending` | Pending positions awaiting resolution |
| `/api/dryrun` | Dry run summary statistics |
| `/api/observations` | Whale observation data |
| `/api/observations/analytics` | Whale performance analytics |
| `/api/health` | System health check |

## Output Files

| File | Contents |
|------|----------|
| `trades.db` | SQLite database with all trade data |
| `trading_stats.json` | Current performance metrics |
| `small_capital_log.jsonl` | Trade-by-trade log |
| `ultra_fast_stats.json` | Discovery system stats |

## Dry Run Mode

By default, `AUTO_COPY_ENABLED=false` runs the system in dry run mode:

- All trade detection and analysis runs normally
- Trades are logged but not executed
- Positions are tracked and resolved based on actual market outcomes
- Capital/ROI calculated against 24-hour committed capital (not static $100)

Set `AUTO_COPY_ENABLED=true` to enable live trading.

## Monitoring

The system prints periodic stats:

```
📊 $100 CAPITAL STATS - 14:32:15
────────────────────────────────────────────
💰 Starting: $100  →  Current: $142.50
📈 ROI: 42.5%  |  Profit: $42.50
📊 Trades: 8  |  Wins: 6  |  Losses: 2
🎯 Win rate: 75.0%  |  Avg profit: $5.31
────────────────────────────────────────────
```

Whale management logs:

```
============================================================
🐋 WHALE MANAGEMENT - Hourly Roster Update
============================================================
   🐋 Promoted 2 top performers from observations to active tier list
   🧹 Pruned 1 whales with win rate below 80%
   📊 Changes: +2 promoted, -1 pruned
   ✅ Reloaded tiers: 26 whales now monitored
   📈 Observations: 45 whales, 312 resolved trades, 73.4% win rate
============================================================
```

## Troubleshooting

### "No whales in tiers"

The database needs market metadata. On first run, it fetches from Gamma API (can take a few minutes for 300 tokens).

### WebSocket disconnects

Normal behavior - the system auto-reconnects with exponential backoff. Falls back to polling if WebSocket consistently fails.

### High threshold rejections

If you see trades rejected at 99% threshold, the whale is trading outside their specialty timeframe. This is intentional - the system is conservative when whales trade outside their area of expertise.

### Position not resolving

Positions are resolved based on actual market outcomes from Gamma API. If a position stays pending longer than expected, the market may not have resolved yet or the API may be delayed.

### Dashboard shows wrong capital

In dry run mode, the dashboard uses 24-hour committed capital instead of static $100. This better reflects actual trading activity since we're not bound by real capital constraints.

## License

MIT
