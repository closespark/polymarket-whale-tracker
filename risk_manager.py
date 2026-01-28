"""
Enhanced Risk Management System

Multi-layer protection for trading capital:
1. Trailing stop-loss (protect profits)
2. Position limits (per trade, per whale, per market)
3. Drawdown protection (reduce size when losing)
4. Time-based rules
5. Win rate monitoring
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional
from collections import defaultdict
import json


class RiskManager:
    """
    Comprehensive risk management for whale copy trading

    Protects capital through multiple layers of controls
    """

    def __init__(self,
                 starting_capital: float = 100,
                 max_drawdown_pct: float = 0.30,
                 max_per_trade_pct: float = 0.15,
                 max_per_whale_pct: float = 0.25,
                 max_per_market_pct: float = 0.35,
                 max_daily_exposure_pct: float = 0.60):
        """
        Initialize risk manager with limits

        Args:
            starting_capital: Initial capital
            max_drawdown_pct: Stop trading if down this much (0.30 = 30%)
            max_per_trade_pct: Max single trade size (0.15 = 15%)
            max_per_whale_pct: Max exposure to single whale (0.25 = 25%)
            max_per_market_pct: Max exposure to single market (0.35 = 35%)
            max_daily_exposure_pct: Max total daily exposure (0.60 = 60%)
        """

        self.starting_capital = starting_capital
        self.current_capital = starting_capital
        self.peak_capital = starting_capital

        # Limits
        self.max_drawdown_pct = max_drawdown_pct
        self.max_per_trade_pct = max_per_trade_pct
        self.max_per_whale_pct = max_per_whale_pct
        self.max_per_market_pct = max_per_market_pct
        self.max_daily_exposure_pct = max_daily_exposure_pct

        # Tracking
        self.open_positions = {}  # position_id -> position_data
        self.whale_exposure = defaultdict(float)  # whale -> total exposure
        self.market_exposure = defaultdict(float)  # market -> total exposure
        self.daily_trades = []  # trades today
        self.trade_history = []

        # Performance tracking
        self.consecutive_losses = 0
        self.consecutive_wins = 0
        self.recent_win_rate = 0.72  # Default assumption

        # Trailing stop state
        self.trailing_stops = {}  # position_id -> stop_price

        # Risk state
        self.risk_state = "NORMAL"  # NORMAL, REDUCED, MINIMAL, STOPPED
        self.risk_reasons = []

        print(f"Risk Manager initialized:")
        print(f"  Max drawdown: {max_drawdown_pct*100}%")
        print(f"  Max per trade: {max_per_trade_pct*100}%")
        print(f"  Max per whale: {max_per_whale_pct*100}%")

    def update_capital(self, new_capital: float):
        """Update current capital and peak"""
        self.current_capital = new_capital
        if new_capital > self.peak_capital:
            self.peak_capital = new_capital

    def get_drawdown(self) -> Dict:
        """Calculate current drawdown from peak and starting"""
        from_peak = (self.peak_capital - self.current_capital) / self.peak_capital
        from_start = (self.starting_capital - self.current_capital) / self.starting_capital

        return {
            'from_peak_pct': round(from_peak * 100, 2),
            'from_start_pct': round(from_start * 100, 2),
            'peak_capital': self.peak_capital,
            'current_capital': self.current_capital
        }

    def can_trade(self) -> Dict:
        """
        Check if trading is allowed based on risk rules

        Returns:
            Dict with 'allowed' bool and 'reasons' list
        """
        reasons = []
        self.risk_reasons = []

        # Check absolute drawdown
        drawdown = self.get_drawdown()
        if drawdown['from_start_pct'] >= self.max_drawdown_pct * 100:
            reasons.append(f"Max drawdown exceeded ({drawdown['from_start_pct']:.1f}%)")
            self.risk_state = "STOPPED"

        # Check consecutive losses
        if self.consecutive_losses >= 5:
            reasons.append(f"5+ consecutive losses ({self.consecutive_losses})")

        # Check recent win rate
        if len(self.trade_history) >= 20:
            recent = self.trade_history[-20:]
            recent_wins = sum(1 for t in recent if t.get('profit', 0) > 0)
            self.recent_win_rate = recent_wins / 20

            if self.recent_win_rate < 0.55:
                reasons.append(f"Win rate dropped to {self.recent_win_rate*100:.0f}%")

        # Check daily exposure
        daily_exposure = self._get_daily_exposure()
        if daily_exposure >= self.current_capital * self.max_daily_exposure_pct:
            reasons.append(f"Daily exposure limit reached (${daily_exposure:.0f})")

        self.risk_reasons = reasons

        return {
            'allowed': len(reasons) == 0,
            'reasons': reasons,
            'risk_state': self.risk_state,
            'drawdown': drawdown,
            'consecutive_losses': self.consecutive_losses,
            'recent_win_rate': self.recent_win_rate
        }

    def check_trade(self, trade_data: Dict, proposed_size: float) -> Dict:
        """
        Check if a specific trade is allowed

        Returns adjusted size and reasons
        """
        whale = trade_data.get('whale_address', '')
        market = trade_data.get('market', '')

        original_size = proposed_size
        reasons = []

        # Check if trading allowed at all
        can_trade = self.can_trade()
        if not can_trade['allowed']:
            return {
                'allowed': False,
                'size': 0,
                'original_size': original_size,
                'reasons': can_trade['reasons']
            }

        # Check per-trade limit
        max_trade = self.current_capital * self.max_per_trade_pct
        if proposed_size > max_trade:
            proposed_size = max_trade
            reasons.append(f"Per-trade limit (${max_trade:.0f})")

        # Check whale exposure
        current_whale_exposure = self.whale_exposure.get(whale, 0)
        max_whale = self.current_capital * self.max_per_whale_pct
        available_whale = max_whale - current_whale_exposure

        if proposed_size > available_whale:
            proposed_size = max(0, available_whale)
            reasons.append(f"Whale exposure limit (${max_whale:.0f})")

        # Check market exposure
        if market:
            current_market_exposure = self.market_exposure.get(market, 0)
            max_market = self.current_capital * self.max_per_market_pct
            available_market = max_market - current_market_exposure

            if proposed_size > available_market:
                proposed_size = max(0, available_market)
                reasons.append(f"Market exposure limit (${max_market:.0f})")

        # Apply drawdown reduction
        drawdown = self.get_drawdown()
        if drawdown['from_start_pct'] >= 20:
            proposed_size *= 0.5
            reasons.append("50% reduction (20%+ drawdown)")
        elif drawdown['from_start_pct'] >= 15:
            proposed_size *= 0.7
            reasons.append("30% reduction (15%+ drawdown)")
        elif drawdown['from_start_pct'] >= 10:
            proposed_size *= 0.85
            reasons.append("15% reduction (10%+ drawdown)")

        # Apply loss streak reduction
        if self.consecutive_losses >= 3:
            proposed_size *= 0.5
            reasons.append(f"50% reduction ({self.consecutive_losses} losses)")
        elif self.consecutive_losses >= 2:
            proposed_size *= 0.75
            reasons.append(f"25% reduction ({self.consecutive_losses} losses)")

        # Round
        proposed_size = round(proposed_size * 2) / 2

        # Minimum check
        if 0 < proposed_size < 2:
            proposed_size = 0
            reasons.append("Below $2 minimum")

        return {
            'allowed': proposed_size > 0,
            'size': proposed_size,
            'original_size': original_size,
            'reduction_pct': round((1 - proposed_size/original_size) * 100, 1) if original_size > 0 else 0,
            'reasons': reasons,
            'risk_state': self.risk_state
        }

    def record_trade_open(self, position_id: str, trade_data: Dict, size: float):
        """Record a new position opening"""
        whale = trade_data.get('whale_address', '')
        market = trade_data.get('market', '')
        entry_price = trade_data.get('price', 0)

        self.open_positions[position_id] = {
            'whale': whale,
            'market': market,
            'size': size,
            'entry_price': entry_price,
            'entry_time': datetime.now(),
            'trade_data': trade_data
        }

        self.whale_exposure[whale] += size
        if market:
            self.market_exposure[market] += size

        # Set initial trailing stop
        self.trailing_stops[position_id] = {
            'stop_price': entry_price * 0.7,  # 30% stop
            'highest_price': entry_price
        }

        self.daily_trades.append({
            'time': datetime.now(),
            'size': size,
            'type': 'open'
        })

    def record_trade_close(self, position_id: str, exit_price: float, profit: float):
        """Record a position closing"""
        if position_id not in self.open_positions:
            return

        position = self.open_positions[position_id]
        whale = position['whale']
        market = position['market']
        size = position['size']

        # Update exposures
        self.whale_exposure[whale] = max(0, self.whale_exposure[whale] - size)
        if market:
            self.market_exposure[market] = max(0, self.market_exposure[market] - size)

        # Update streaks
        if profit > 0:
            self.consecutive_wins += 1
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1
            self.consecutive_wins = 0

        # Record history
        self.trade_history.append({
            'time': datetime.now(),
            'profit': profit,
            'size': size,
            'whale': whale
        })

        # Cleanup
        del self.open_positions[position_id]
        if position_id in self.trailing_stops:
            del self.trailing_stops[position_id]

        self.daily_trades.append({
            'time': datetime.now(),
            'profit': profit,
            'type': 'close'
        })

    def update_trailing_stop(self, position_id: str, current_price: float) -> Dict:
        """
        Update trailing stop for a position

        Returns action to take if stop triggered
        """
        if position_id not in self.trailing_stops:
            return {'action': None}

        stop_data = self.trailing_stops[position_id]
        position = self.open_positions.get(position_id, {})
        entry_price = position.get('entry_price', current_price)

        # Update highest price
        if current_price > stop_data['highest_price']:
            stop_data['highest_price'] = current_price

            # Trail the stop up (but never down)
            # Stop at 70% of highest or 90% of profit, whichever is higher
            profit_so_far = current_price - entry_price
            if profit_so_far > 0:
                # Protect 80% of profit
                profit_protected_stop = entry_price + (profit_so_far * 0.8)
                stop_data['stop_price'] = max(stop_data['stop_price'], profit_protected_stop)

        # Check if stop triggered
        if current_price <= stop_data['stop_price']:
            return {
                'action': 'CLOSE',
                'reason': 'Trailing stop triggered',
                'stop_price': stop_data['stop_price'],
                'current_price': current_price,
                'highest_price': stop_data['highest_price']
            }

        return {
            'action': None,
            'stop_price': stop_data['stop_price'],
            'highest_price': stop_data['highest_price'],
            'distance_to_stop': round((current_price - stop_data['stop_price']) / current_price * 100, 1)
        }

    def should_skip_trade_by_time(self, market_data: Dict = None) -> Dict:
        """
        Check if trade should be skipped based on time rules

        Rules:
        - No trading in first 30 seconds (market settling)
        - No trading in last 2 minutes (low liquidity)
        - Reduce size after 10 PM (less activity)
        """
        reasons = []
        multiplier = 1.0

        if market_data:
            time_remaining = market_data.get('time_remaining_minutes', 999)

            if time_remaining < 2:
                reasons.append("Last 2 minutes - skip trade")
                return {'skip': True, 'reasons': reasons}

            elif time_remaining < 5:
                multiplier = 0.5
                reasons.append("Last 5 minutes - 50% size")

            time_elapsed = market_data.get('time_elapsed_seconds', 999)
            if time_elapsed < 30:
                reasons.append("First 30 seconds - skip trade")
                return {'skip': True, 'reasons': reasons}

        # Check time of day
        hour = datetime.now().hour
        if hour >= 22 or hour < 6:  # 10 PM - 6 AM
            multiplier *= 0.7
            reasons.append("Late night - 30% reduction")

        return {
            'skip': False,
            'multiplier': multiplier,
            'reasons': reasons
        }

    def _get_daily_exposure(self) -> float:
        """Get total exposure opened today"""
        today = datetime.now().date()
        return sum(
            t['size'] for t in self.daily_trades
            if t['time'].date() == today and t['type'] == 'open'
        )

    def _cleanup_old_daily_trades(self):
        """Remove trades older than today"""
        today = datetime.now().date()
        self.daily_trades = [
            t for t in self.daily_trades
            if t['time'].date() == today
        ]

    def get_risk_report(self) -> Dict:
        """Get comprehensive risk status report"""
        drawdown = self.get_drawdown()
        daily_exposure = self._get_daily_exposure()

        return {
            'risk_state': self.risk_state,
            'risk_reasons': self.risk_reasons,

            'capital': {
                'starting': self.starting_capital,
                'current': self.current_capital,
                'peak': self.peak_capital
            },

            'drawdown': {
                'from_peak_pct': drawdown['from_peak_pct'],
                'from_start_pct': drawdown['from_start_pct'],
                'max_allowed': self.max_drawdown_pct * 100
            },

            'exposure': {
                'open_positions': len(self.open_positions),
                'total_open': sum(p['size'] for p in self.open_positions.values()),
                'daily_exposure': daily_exposure,
                'daily_limit': self.current_capital * self.max_daily_exposure_pct,
                'whale_exposure': dict(self.whale_exposure),
                'market_exposure': dict(self.market_exposure)
            },

            'performance': {
                'consecutive_losses': self.consecutive_losses,
                'consecutive_wins': self.consecutive_wins,
                'recent_win_rate': round(self.recent_win_rate * 100, 1),
                'total_trades': len(self.trade_history)
            },

            'limits': {
                'max_per_trade_pct': self.max_per_trade_pct * 100,
                'max_per_whale_pct': self.max_per_whale_pct * 100,
                'max_per_market_pct': self.max_per_market_pct * 100,
                'max_daily_exposure_pct': self.max_daily_exposure_pct * 100
            }
        }

    def save_report(self, filepath: str = 'risk_report.json'):
        """Save risk report to file"""
        report = self.get_risk_report()
        report['timestamp'] = datetime.now().isoformat()

        with open(filepath, 'w') as f:
            json.dump(report, f, indent=2, default=str)


if __name__ == "__main__":
    print("="*60)
    print("RISK MANAGER DEMO")
    print("="*60)

    rm = RiskManager(starting_capital=100)

    # Simulate some trades
    trade_data = {
        'whale_address': '0x1234',
        'market': 'BTC > 100k?',
        'price': 0.65
    }

    # Check trade
    check = rm.check_trade(trade_data, proposed_size=15)
    print(f"\nTrade check:")
    print(f"  Allowed: {check['allowed']}")
    print(f"  Size: ${check['size']} (from ${check['original_size']})")
    print(f"  Reasons: {check['reasons']}")

    # Simulate winning
    rm.record_trade_open('pos1', trade_data, check['size'])
    rm.update_capital(110)
    rm.record_trade_close('pos1', 0.80, 10)

    # Get report
    report = rm.get_risk_report()
    print(f"\nRisk Report:")
    print(f"  State: {report['risk_state']}")
    print(f"  Capital: ${report['capital']['current']}")
    print(f"  Consecutive wins: {report['performance']['consecutive_wins']}")

    print("\n" + "="*60)
