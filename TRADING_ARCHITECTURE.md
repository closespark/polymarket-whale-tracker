# Polymarket Trading Architecture Design

## Overview

This document outlines the complete trading lifecycle for the whale copy-trading system,
from detecting a whale trade to recognizing profit/loss when a market resolves.

## Current State (What Exists)

1. **Whale Detection** ✅ - WebSocket monitoring of OrderFilled events
2. **Trade Scoring** ✅ - Confidence calculation based on whale history
3. **Position Sizing** ✅ - Kelly Criterion sizing
4. **Dry Run Simulation** ✅ - Simulated P&L with random outcomes

## What's Missing

1. **Order Placement** - Actually buying outcome tokens
2. **Position Tracking** - Knowing what we own (token_id, quantity, cost basis)
3. **Market Resolution Detection** - Knowing when a market closes and the outcome
4. **Profit Recognition** - Detecting USDC balance changes after resolution

---

## Architecture Components

### 1. PositionManager (New)

Manages our actual positions on Polymarket.

```
┌─────────────────────────────────────────────────────────────────┐
│                     PositionManager                              │
├─────────────────────────────────────────────────────────────────┤
│ Responsibilities:                                                │
│ - Place orders via CLOB API                                     │
│ - Track open positions (token_id, quantity, avg_price)          │
│ - Query conditional token balances                              │
│ - Record cost basis for P&L calculation                         │
├─────────────────────────────────────────────────────────────────┤
│ Data Stored per Position:                                       │
│ - position_id: unique identifier                                │
│ - token_id: the outcome token we bought                         │
│ - condition_id: the market's condition                          │
│ - market_slug: human-readable market name                       │
│ - side: YES or NO (which outcome we bought)                     │
│ - quantity: number of tokens                                    │
│ - avg_entry_price: our average cost per token                   │
│ - total_cost: USDC spent                                        │
│ - opened_at: when we entered                                    │
│ - expected_resolution: when market should resolve               │
│ - status: PENDING | RESOLVED | CANCELLED                        │
│ - resolution_outcome: WIN | LOSS | null                         │
│ - pnl: profit/loss after resolution                             │
└─────────────────────────────────────────────────────────────────┘
```

### 2. OrderExecutor (New)

Handles the actual order placement with the CLOB.

```
┌─────────────────────────────────────────────────────────────────┐
│                      OrderExecutor                               │
├─────────────────────────────────────────────────────────────────┤
│ Responsibilities:                                                │
│ - Build order parameters (token_id, price, size)                │
│ - Fetch nonce from API                                          │
│ - Sign and submit order via py-clob-client                      │
│ - Handle order confirmation/rejection                           │
│ - Retry logic for failed orders                                 │
├─────────────────────────────────────────────────────────────────┤
│ Order Flow:                                                      │
│ 1. Receive trade_data from whale detection                      │
│ 2. Calculate order size based on position_size (USDC)           │
│ 3. Get current market price from order book                     │
│ 4. Fetch nonce from API                                         │
│ 5. Create and sign order                                        │
│ 6. Submit to CLOB                                               │
│ 7. Return order_id and fill status                              │
└─────────────────────────────────────────────────────────────────┘
```

### 3. MarketResolver (New)

Monitors markets for resolution and updates positions.

```
┌─────────────────────────────────────────────────────────────────┐
│                      MarketResolver                              │
├─────────────────────────────────────────────────────────────────┤
│ Responsibilities:                                                │
│ - Poll markets for resolution status                            │
│ - Detect when a market has resolved                             │
│ - Determine outcome (YES won, NO won)                           │
│ - Update position status                                        │
│ - Trigger P&L calculation                                       │
├─────────────────────────────────────────────────────────────────┤
│ Resolution Detection Methods:                                    │
│                                                                  │
│ Method 1: Poll Gamma API                                        │
│   - GET /markets?condition_id={id}                              │
│   - Check for 'resolved' or 'closed' status                     │
│   - Check 'outcome' field                                       │
│                                                                  │
│ Method 2: Watch blockchain events                               │
│   - PayoutRedemption events on CTF contract                     │
│   - Indicates market resolved and payout occurred               │
│                                                                  │
│ Method 3: Balance change detection                              │
│   - If outcome token balance goes to 0 AND USDC increases       │
│   - Market resolved and we won                                  │
│   - If outcome token balance goes to 0 AND no USDC increase     │
│   - Market resolved and we lost                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 4. BalanceTracker (New)

Monitors wallet balances for position verification and P&L.

```
┌─────────────────────────────────────────────────────────────────┐
│                      BalanceTracker                              │
├─────────────────────────────────────────────────────────────────┤
│ Responsibilities:                                                │
│ - Query USDC balance                                            │
│ - Query conditional token balances for each position            │
│ - Detect balance changes after resolution                       │
│ - Calculate realized P&L                                        │
├─────────────────────────────────────────────────────────────────┤
│ Balance Queries:                                                 │
│                                                                  │
│ USDC Balance:                                                   │
│   contract.functions.balanceOf(funder_address).call()           │
│                                                                  │
│ Outcome Token Balance:                                          │
│   ctf_contract.functions.balanceOf(funder_address, token_id)    │
│                                                                  │
│ P&L Calculation:                                                │
│   If we hold YES tokens and YES wins:                           │
│     pnl = quantity * 1.0 - total_cost                           │
│   If we hold YES tokens and NO wins:                            │
│     pnl = -total_cost (we lost our cost basis)                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Complete Trade Lifecycle

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          TRADE LIFECYCLE                                  │
└──────────────────────────────────────────────────────────────────────────┘

1. WHALE DETECTION
   ┌─────────────────────────────────────────────────────────────────────┐
   │ WebSocket receives OrderFilled event                                │
   │ → Extract whale_address, token_id, side, amount                     │
   │ → Aggregate trades (filter arbitrage)                               │
   │ → Forward to trade processor                                        │
   └─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
2. TRADE EVALUATION
   ┌─────────────────────────────────────────────────────────────────────┐
   │ Calculate confidence score                                          │
   │ → Check whale tier and win rate                                     │
   │ → Apply multi-timeframe strategy                                    │
   │ → Calculate Kelly-optimal position size                             │
   │ → Decision: COPY or SKIP                                            │
   └─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼ (if COPY)
3. ORDER PLACEMENT
   ┌─────────────────────────────────────────────────────────────────────┐
   │ OrderExecutor.place_order(token_id, side, usdc_amount)              │
   │ → Lookup market info (condition_id, end_date)                       │
   │ → Get current price from order book                                 │
   │ → Calculate token quantity: usdc_amount / price                     │
   │ → Fetch nonce from CLOB API                                         │
   │ → Sign order with EIP-712                                           │
   │ → Submit order to CLOB                                              │
   │ → Return order_id, fill_price, fill_quantity                        │
   └─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
4. POSITION RECORDING
   ┌─────────────────────────────────────────────────────────────────────┐
   │ PositionManager.record_position(...)                                │
   │ → Store: token_id, condition_id, quantity, cost_basis               │
   │ → Store: expected_resolution (from market end_date)                 │
   │ → Status: PENDING                                                   │
   │ → Verify balance: conditional token balance matches                 │
   └─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
5. POSITION MONITORING (Continuous)
   ┌─────────────────────────────────────────────────────────────────────┐
   │ MarketResolver runs every 30 seconds                                │
   │ For each PENDING position:                                          │
   │ → Check if current_time > expected_resolution                       │
   │ → If yes, query market resolution status                            │
   │ → Poll Gamma API: GET /markets?condition_id={id}                    │
   │ → Check for resolved=true and outcome field                         │
   └─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼ (when market resolves)
6. RESOLUTION DETECTION
   ┌─────────────────────────────────────────────────────────────────────┐
   │ Market resolved - determine outcome                                 │
   │ → outcome = "YES" or "NO"                                           │
   │ → Our position: side = "YES" or "NO"                                │
   │ → WIN if outcome == our_side                                        │
   │ → LOSS if outcome != our_side                                       │
   └─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
7. P&L CALCULATION
   ┌─────────────────────────────────────────────────────────────────────┐
   │ BalanceTracker.calculate_pnl(position)                              │
   │                                                                     │
   │ If WIN:                                                             │
   │   → Tokens redeem at $1.00 each                                     │
   │   → pnl = (quantity * 1.0) - total_cost                             │
   │   → Example: Bought 100 tokens at $0.65 = $65 cost                  │
   │   →          Win: 100 * $1.00 = $100 return                         │
   │   →          PnL = $100 - $65 = +$35                                │
   │                                                                     │
   │ If LOSS:                                                            │
   │   → Tokens worth $0.00                                              │
   │   → pnl = -total_cost                                               │
   │   → Example: Bought 100 tokens at $0.65 = $65 cost                  │
   │   →          Loss: tokens worth $0                                  │
   │   →          PnL = -$65                                             │
   └─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
8. STATS UPDATE
   ┌─────────────────────────────────────────────────────────────────────┐
   │ Update system stats                                                 │
   │ → current_capital += pnl                                            │
   │ → wins/losses count                                                 │
   │ → Position status: RESOLVED                                         │
   │ → Log trade result                                                  │
   └─────────────────────────────────────────────────────────────────────┘
```

---

## Data Structures

### Position Record (SQLite or JSON)

```python
position = {
    # Identity
    'id': 'pos_abc123',
    'order_id': 'ord_xyz789',

    # Market Info
    'token_id': '12345...',           # The outcome token
    'condition_id': '67890...',        # The market condition
    'market_slug': 'btc-100k-jan',
    'market_question': 'Will BTC reach $100k by Jan?',
    'expected_resolution': '2024-01-15T15:00:00Z',

    # Position Details
    'side': 'YES',                     # Which outcome we bought
    'quantity': 100.0,                 # Number of tokens
    'entry_price': 0.65,               # Price per token
    'total_cost': 65.0,                # USDC spent

    # Tracking
    'whale_address': '0x123...',       # Who we copied
    'whale_trade_block': 12345678,
    'confidence': 92.5,
    'opened_at': '2024-01-15T10:30:00Z',

    # Resolution
    'status': 'PENDING',               # PENDING | RESOLVED | CANCELLED
    'resolved_at': null,
    'outcome': null,                   # YES | NO (market result)
    'is_win': null,                    # true | false
    'pnl': null,                       # Profit/loss in USDC
}
```

### Order Request

```python
order_request = {
    'token_id': '12345...',
    'side': 'BUY',
    'price': 0.65,                     # Max price willing to pay
    'size': 100.0,                     # Number of tokens
    'order_type': 'GTC',               # Good-til-cancelled
}
```

---

## Implementation Plan

### Phase 1: Order Execution (order_executor.py)
- [ ] Initialize ClobClient with credentials
- [ ] Implement `get_market_price()` - fetch current best price
- [ ] Implement `place_order()` - sign and submit order
- [ ] Implement `check_order_status()` - verify fill
- [ ] Add retry logic and error handling

### Phase 2: Position Management (position_manager.py)
- [ ] SQLite table for positions
- [ ] Implement `record_position()` - store new position
- [ ] Implement `get_pending_positions()` - list open positions
- [ ] Implement `update_position_status()` - mark resolved

### Phase 3: Market Resolution (market_resolver.py)
- [ ] Implement `check_market_resolution()` - poll Gamma API
- [ ] Implement resolution loop - check pending positions
- [ ] Parse resolution outcome (YES/NO)
- [ ] Trigger P&L calculation on resolution

### Phase 4: Balance Tracking (balance_tracker.py)
- [ ] Query USDC balance
- [ ] Query conditional token balances
- [ ] Detect balance changes post-resolution
- [ ] Verify expected vs actual P&L

### Phase 5: Integration
- [ ] Replace `PendingPositionTracker` simulation with real execution
- [ ] Update `SmallCapitalSystem` to use new components
- [ ] Add monitoring dashboard for open positions
- [ ] Comprehensive logging for audit trail

---

## API Reference

### Gamma API (Market Data)

```
Base URL: https://gamma-api.polymarket.com

GET /markets?condition_id={id}
→ Returns market info including resolution status

GET /markets?clob_token_ids={token_id}
→ Returns market info for a specific token

Response includes:
- question: Market question text
- end_date_iso: When market ends
- resolved: true/false
- outcome: "YES" | "NO" (after resolution)
```

### CLOB API (Trading)

```
Base URL: https://clob.polymarket.com

Via py-clob-client:

client.create_order(order_args)
→ Places a new order, returns order_id

client.get_orders()
→ Returns list of open orders

client.cancel_order(order_id)
→ Cancels an open order
```

### Blockchain Queries

```python
# USDC Balance
usdc_contract.functions.balanceOf(address).call()

# Outcome Token Balance
ctf_contract.functions.balanceOf(address, token_id).call()

# Events to watch:
- OrderFilled: Trade executed
- PayoutRedemption: Market resolved and payout claimed
```

---

## Risk Considerations

1. **Order Slippage**: Price may move between detection and execution
   - Mitigation: Use limit orders with slight premium

2. **Failed Orders**: Network issues or insufficient balance
   - Mitigation: Retry logic, balance pre-check

3. **Missed Resolution**: API down when market resolves
   - Mitigation: Balance-based detection as backup

4. **Double Counting**: Same position counted twice
   - Mitigation: Unique position_id, deduplication

5. **Gas Costs**: On-chain operations cost MATIC
   - Mitigation: Batch operations, minimum position sizes
