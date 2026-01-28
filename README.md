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
│  • Tier assignment                                       │
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

## Installation

### Prerequisites

- Python 3.9+
- Polygon RPC endpoint (Alchemy recommended for WebSocket support)

### Setup

```bash
# Clone and install dependencies
pip install web3 websockets python-dotenv requests pandas anthropic

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

## Key Files

| File | Purpose |
|------|---------|
| `small_capital_system.py` | Main orchestrator - runs all components |
| `ultra_fast_discovery.py` | Incremental blockchain scanning, SQLite storage |
| `websocket_monitor.py` | Real-time WebSocket event subscriptions |
| `multi_timeframe_strategy.py` | Tier system, threshold calculation |
| `trade_database.py` | SQLite storage, timeframe analysis, Gamma API |
| `whale_intelligence.py` | Correlation detection, market maker filtering |
| `kelly_sizing.py` | Kelly Criterion position sizing |
| `risk_manager.py` | Drawdown limits, exposure management |
| `claude_validator.py` | Claude AI trade validation (optional) |
| `config.py` | Configuration and contract ABIs |

## Database Schema

The system uses SQLite (`trades.db`) with these key tables:

- **trades** - All OrderFilled events from CTF Exchange
- **market_metadata** - Token ID → timeframe mapping (from Gamma API)
- **whale_timeframe_stats** - Cached tier assignments

## Tier System Details

### How Whales Are Assigned to Tiers

1. **Market metadata fetch** - Polymarket Gamma API provides market questions
2. **Timeframe inference** - Keywords like "15 min", "hourly", "daily" determine category
3. **SQL analysis** - Aggregates win rate by trader by timeframe
4. **Tier assignment** - Top performers in each timeframe join respective tier

### Tier Requirements

| Tier | Min Trades | Min Win Rate | Max Whales |
|------|------------|--------------|------------|
| 15min | 20 | 75% | 15 |
| hourly | 15 | 73% | 15 |
| 4hour | 10 | 72% | 10 |
| daily | 10 | 70% | 10 |

## Risk Management

- **Max per trade**: 15% of capital
- **Max per whale**: 25% of capital
- **Max daily exposure**: 60% of capital
- **Stop-loss**: 30% drawdown triggers system halt
- **Kelly fraction**: 0.25 (quarter Kelly for safety)

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
- Simulated P&L calculated based on confidence levels

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

## Troubleshooting

### "No whales in tiers"

The database needs market metadata. On first run, it fetches from Gamma API (can take a few minutes for 300 tokens).

### WebSocket disconnects

Normal behavior - the system auto-reconnects with exponential backoff. Falls back to polling if WebSocket consistently fails.

### High threshold rejections

If you see trades rejected at 99% threshold, the whale is trading outside their specialty timeframe. This is intentional - the system is conservative when whales trade outside their area of expertise.

## License

MIT
