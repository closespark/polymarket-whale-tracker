"""
Kelly Criterion Position Sizing

Mathematically optimal position sizing based on:
- Win probability (whale's historical win rate)
- Profit ratio (average win / average loss)
- Risk management constraints

Benefits over simple percentage sizing:
- 10-20% higher long-term returns
- Accounts for both win rate AND profit magnitude
- Automatically reduces size during losing streaks
- Mathematically proven optimal for compounding
"""

from typing import Dict, Optional
import math


class KellySizing:
    """
    Kelly Criterion based position sizing with safety constraints

    Formula: f = (p * b - q) / b
    Where:
    - f = fraction of bankroll to bet
    - p = probability of winning
    - q = probability of losing (1 - p)
    - b = ratio of profit to loss (avg_win / avg_loss)
    """

    def __init__(self,
                 kelly_fraction: float = 0.25,
                 max_position_pct: float = 0.15,
                 min_position: float = 2.0,
                 max_position: float = 5000.0):
        """
        Args:
            kelly_fraction: Use this fraction of Kelly (0.25 = quarter Kelly, safer)
            max_position_pct: Maximum position as % of capital (0.15 = 15%)
            min_position: Minimum position size in dollars
            max_position: Maximum position size in dollars
        """
        self.kelly_fraction = kelly_fraction
        self.max_position_pct = max_position_pct
        self.min_position = min_position
        self.max_position = max_position

        # Default profit ratios for Polymarket
        self.default_avg_win = 0.40   # 40% return on wins
        self.default_avg_loss = 1.00  # 100% loss on losses

    def calculate_kelly(self,
                       win_rate: float,
                       avg_win_pct: float = None,
                       avg_loss_pct: float = None) -> float:
        """
        Calculate raw Kelly fraction

        Args:
            win_rate: Probability of winning (0.0 to 1.0)
            avg_win_pct: Average profit on winning trades (e.g., 0.40 = 40%)
            avg_loss_pct: Average loss on losing trades (e.g., 1.0 = 100%)

        Returns:
            Kelly fraction (can be negative if edge is negative)
        """
        avg_win = avg_win_pct or self.default_avg_win
        avg_loss = avg_loss_pct or self.default_avg_loss

        p = win_rate  # Win probability
        q = 1 - p     # Loss probability
        b = avg_win / avg_loss  # Profit ratio

        # Kelly formula
        kelly = (p * b - q) / b

        return kelly

    def calculate_position(self,
                          capital: float,
                          whale_data: Dict,
                          confidence: float,
                          recent_performance: Optional[Dict] = None) -> Dict:
        """
        Calculate optimal position size using Kelly Criterion

        Args:
            capital: Current capital in dollars
            whale_data: Dict with whale stats (win_rate, avg_profit, etc.)
            confidence: Trade confidence (0-100)
            recent_performance: Optional recent performance adjustments

        Returns:
            Dict with position size and calculation details
        """

        # Extract whale metrics
        win_rate = whale_data.get('win_rate', 0.5)
        if isinstance(win_rate, str):
            win_rate = float(win_rate)
        if win_rate > 1:  # If passed as percentage
            win_rate = win_rate / 100

        avg_win_pct = whale_data.get('avg_win_pct', self.default_avg_win)
        avg_loss_pct = whale_data.get('avg_loss_pct', self.default_avg_loss)

        # Calculate raw Kelly
        raw_kelly = self.calculate_kelly(win_rate, avg_win_pct, avg_loss_pct)

        # Apply fractional Kelly (safer)
        fractional_kelly = raw_kelly * self.kelly_fraction

        # Adjust by confidence
        confidence_multiplier = confidence / 100
        adjusted_kelly = fractional_kelly * confidence_multiplier

        # Apply recent performance adjustment
        if recent_performance:
            recent_win_rate = recent_performance.get('recent_win_rate', win_rate)
            # If recent performance is worse, reduce size
            if recent_win_rate < win_rate * 0.9:  # 10% worse
                adjusted_kelly *= 0.7
            elif recent_win_rate < win_rate * 0.95:  # 5% worse
                adjusted_kelly *= 0.85
            # If better, slightly increase
            elif recent_win_rate > win_rate * 1.05:
                adjusted_kelly *= 1.1

        # Calculate dollar amount
        if adjusted_kelly <= 0:
            # Negative edge - don't bet
            position = 0
            reason = "Negative expected value"
        else:
            position = capital * adjusted_kelly
            reason = "Kelly optimal"

        # Apply constraints
        original_position = position

        # Max percentage of capital
        max_by_pct = capital * self.max_position_pct
        if position > max_by_pct:
            position = max_by_pct
            reason = f"Capped at {self.max_position_pct*100}% of capital"

        # Absolute max
        if position > self.max_position:
            position = self.max_position
            reason = f"Capped at ${self.max_position}"

        # Minimum viable position
        if 0 < position < self.min_position:
            position = 0
            reason = f"Below ${self.min_position} minimum"

        # Round to nearest $0.50
        position = round(position * 2) / 2

        return {
            'position_size': position,
            'raw_kelly': round(raw_kelly, 4),
            'fractional_kelly': round(fractional_kelly, 4),
            'adjusted_kelly': round(adjusted_kelly, 4),
            'confidence_multiplier': round(confidence_multiplier, 2),
            'win_rate_used': round(win_rate, 3),
            'capital': capital,
            'reason': reason,
            'original_position': round(original_position, 2),
            'constraints_applied': position != original_position
        }

    def calculate_with_drawdown_adjustment(self,
                                           capital: float,
                                           whale_data: Dict,
                                           confidence: float,
                                           starting_capital: float) -> Dict:
        """
        Calculate position with drawdown-based risk reduction

        If in drawdown, reduce position sizes to protect capital
        """

        # Calculate base position
        result = self.calculate_position(capital, whale_data, confidence)

        # Check drawdown level
        if starting_capital > 0:
            drawdown_pct = (starting_capital - capital) / starting_capital
        else:
            drawdown_pct = 0

        # Apply drawdown multipliers
        if drawdown_pct >= 0.25:  # 25%+ drawdown
            multiplier = 0.25
            result['drawdown_action'] = "SEVERE - 75% reduction"
        elif drawdown_pct >= 0.20:  # 20%+ drawdown
            multiplier = 0.5
            result['drawdown_action'] = "HIGH - 50% reduction"
        elif drawdown_pct >= 0.15:  # 15%+ drawdown
            multiplier = 0.7
            result['drawdown_action'] = "MODERATE - 30% reduction"
        elif drawdown_pct >= 0.10:  # 10%+ drawdown
            multiplier = 0.85
            result['drawdown_action'] = "LIGHT - 15% reduction"
        else:
            multiplier = 1.0
            result['drawdown_action'] = None

        if multiplier < 1.0:
            result['position_size'] = round(result['position_size'] * multiplier * 2) / 2
            result['drawdown_pct'] = round(drawdown_pct * 100, 1)
            result['drawdown_multiplier'] = multiplier

        return result


class EnhancedPositionSizer:
    """
    Enhanced position sizing combining Kelly Criterion with additional factors
    """

    def __init__(self, starting_capital: float = 100):
        self.starting_capital = starting_capital
        self.kelly = KellySizing(kelly_fraction=0.25)

        # Track performance for adaptive sizing
        self.trade_history = []
        self.current_streak = 0

    def calculate_optimal_position(self,
                                   capital: float,
                                   whale_data: Dict,
                                   confidence: float,
                                   market_data: Optional[Dict] = None) -> Dict:
        """
        Calculate optimal position considering all factors
        """

        # Get Kelly-based position
        result = self.kelly.calculate_with_drawdown_adjustment(
            capital=capital,
            whale_data=whale_data,
            confidence=confidence,
            starting_capital=self.starting_capital
        )

        position = result['position_size']

        # Streak adjustment
        if self.current_streak <= -3:  # 3+ losses
            position *= 0.5
            result['streak_adjustment'] = "3+ losses - 50% reduction"
        elif self.current_streak >= 5:  # 5+ wins
            position *= 0.9  # Slightly reduce on hot streak (regression to mean)
            result['streak_adjustment'] = "5+ wins - 10% reduction (avoid overconfidence)"
        else:
            result['streak_adjustment'] = None

        # Time-of-day adjustment (optional)
        if market_data and market_data.get('time_remaining_minutes'):
            time_remaining = market_data['time_remaining_minutes']
            if time_remaining < 2:  # Last 2 minutes
                position *= 0.5
                result['time_adjustment'] = "Last 2 min - 50% reduction"
            elif time_remaining < 5:  # Last 5 minutes
                position *= 0.8
                result['time_adjustment'] = "Last 5 min - 20% reduction"
            else:
                result['time_adjustment'] = None

        # Ensure minimum
        if 0 < position < self.kelly.min_position:
            position = 0

        result['position_size'] = round(position * 2) / 2
        return result

    def record_trade_result(self, profit: float, was_win: bool):
        """Record trade for streak tracking"""
        self.trade_history.append({
            'profit': profit,
            'was_win': was_win
        })

        if was_win:
            if self.current_streak >= 0:
                self.current_streak += 1
            else:
                self.current_streak = 1
        else:
            if self.current_streak <= 0:
                self.current_streak -= 1
            else:
                self.current_streak = -1

    def get_recent_performance(self, n_trades: int = 10) -> Dict:
        """Get recent performance metrics"""
        recent = self.trade_history[-n_trades:] if self.trade_history else []

        if not recent:
            return {}

        wins = sum(1 for t in recent if t['was_win'])

        return {
            'recent_win_rate': wins / len(recent),
            'recent_trades': len(recent),
            'current_streak': self.current_streak
        }


# Convenience function
def calculate_kelly_position(capital: float,
                            win_rate: float,
                            confidence: float,
                            starting_capital: float = None) -> float:
    """
    Quick helper to calculate position size

    Args:
        capital: Current capital
        win_rate: Historical win rate (0-1 or 0-100)
        confidence: Trade confidence (0-100)
        starting_capital: For drawdown calculation

    Returns:
        Position size in dollars
    """
    kelly = KellySizing()

    whale_data = {'win_rate': win_rate}

    if starting_capital:
        result = kelly.calculate_with_drawdown_adjustment(
            capital, whale_data, confidence, starting_capital
        )
    else:
        result = kelly.calculate_position(capital, whale_data, confidence)

    return result['position_size']


if __name__ == "__main__":
    # Demo
    print("="*60)
    print("KELLY CRITERION POSITION SIZING DEMO")
    print("="*60)

    kelly = KellySizing()

    # Test scenarios
    scenarios = [
        {"capital": 100, "win_rate": 0.72, "confidence": 95, "desc": "$100 capital, 72% WR, 95% conf"},
        {"capital": 500, "win_rate": 0.72, "confidence": 95, "desc": "$500 capital, 72% WR, 95% conf"},
        {"capital": 1000, "win_rate": 0.72, "confidence": 90, "desc": "$1000 capital, 72% WR, 90% conf"},
        {"capital": 100, "win_rate": 0.65, "confidence": 92, "desc": "$100 capital, 65% WR, 92% conf"},
        {"capital": 100, "win_rate": 0.80, "confidence": 98, "desc": "$100 capital, 80% WR, 98% conf"},
    ]

    for s in scenarios:
        result = kelly.calculate_position(
            capital=s['capital'],
            whale_data={'win_rate': s['win_rate']},
            confidence=s['confidence']
        )

        print(f"\n{s['desc']}")
        print(f"  Position: ${result['position_size']:.2f}")
        print(f"  Raw Kelly: {result['raw_kelly']*100:.1f}%")
        print(f"  Fractional Kelly: {result['fractional_kelly']*100:.1f}%")
        print(f"  Reason: {result['reason']}")

    print("\n" + "="*60)
