"""
Adaptive Position Sizing System
Automatically raises position caps as capital grows

90-Day Growth Plan:
- Days 1-7:   Caps at $25
- Days 8-14:  Caps at $50
- Days 15-21: Caps at $100
- Days 22-30: Caps at $200
- Days 31-45: Caps at $400
- Days 46-60: Caps at $800
- Days 61-75: Caps at $1,500
- Days 76-90: Caps at $3,000

As capital grows, position limits grow automatically
"""

from datetime import datetime, timedelta
import json


class AdaptivePositionSizing:
    """
    Automatically adjusts position size caps based on:
    1. Current capital (most important)
    2. Days since start
    3. Win rate performance
    4. Risk management
    """
    
    def __init__(self, starting_capital=100):
        self.starting_capital = starting_capital
        self.current_capital = starting_capital
        self.start_date = datetime.now()
        
        # Track performance for adaptive adjustments
        self.total_trades = 0
        self.winning_trades = 0
        self.total_profit = 0
        
        # Position size history
        self.cap_history = []
        
    def get_days_elapsed(self):
        """Days since system started"""
        return (datetime.now() - self.start_date).days
    
    def get_win_rate(self):
        """Current win rate"""
        if self.total_trades == 0:
            return 0
        return self.winning_trades / self.total_trades
    
    def get_position_cap(self):
        """
        Calculate current position cap based on multiple factors
        
        Primary driver: CAPITAL MILESTONES
        Secondary: Days elapsed (prevents too-fast scaling)
        Tertiary: Win rate (safety check)
        """
        
        capital = self.current_capital
        days = self.get_days_elapsed()
        win_rate = self.get_win_rate()
        
        # CAPITAL-BASED CAPS (Primary)
        if capital >= 50000:
            base_cap = 5000      # $50k+ capital
        elif capital >= 25000:
            base_cap = 3000      # $25k+ capital
        elif capital >= 15000:
            base_cap = 2000      # $15k+ capital
        elif capital >= 10000:
            base_cap = 1500      # $10k+ capital
        elif capital >= 5000:
            base_cap = 800       # $5k+ capital
        elif capital >= 2500:
            base_cap = 400       # $2.5k+ capital
        elif capital >= 1000:
            base_cap = 200       # $1k+ capital
        elif capital >= 500:
            base_cap = 100       # $500+ capital
        elif capital >= 250:
            base_cap = 50        # $250+ capital
        else:
            base_cap = 25        # < $250 capital
        
        # TIME-BASED SAFETY (Prevents too-fast scaling)
        # Don't let cap exceed what time-based schedule allows
        if days < 7:
            time_cap = 25
        elif days < 14:
            time_cap = 50
        elif days < 21:
            time_cap = 100
        elif days < 30:
            time_cap = 200
        elif days < 45:
            time_cap = 400
        elif days < 60:
            time_cap = 800
        elif days < 75:
            time_cap = 1500
        else:
            time_cap = 5000
        
        # Use the LOWER of the two
        cap = min(base_cap, time_cap)
        
        # WIN RATE SAFETY CHECK
        # If win rate drops, reduce cap temporarily
        if self.total_trades >= 20:  # Need enough data
            if win_rate < 0.60:
                cap = cap * 0.5  # Cut in half if < 60%
            elif win_rate < 0.65:
                cap = cap * 0.7  # Reduce 30% if < 65%
            elif win_rate < 0.70:
                cap = cap * 0.85  # Reduce 15% if < 70%
        
        # NEVER exceed 20% of capital in single trade
        absolute_max = capital * 0.20
        cap = min(cap, absolute_max)
        
        # NEVER go below $2 minimum
        cap = max(2, cap)
        
        return int(cap)
    
    def calculate_position_size(self, confidence):
        """
        Calculate position size for a given confidence level
        
        Returns actual dollar amount to copy
        """
        
        # Base percentages by confidence
        if confidence >= 98:
            percent = 0.10      # 10% of capital
        elif confidence >= 95:
            percent = 0.08      # 8% of capital
        elif confidence >= 92:
            percent = 0.06      # 6% of capital
        elif confidence >= 90:
            percent = 0.04      # 4% of capital
        else:
            return 0  # Don't trade below 90%
        
        # Calculate base position
        position = self.current_capital * percent
        
        # Apply cap
        cap = self.get_position_cap()
        position = min(position, cap)
        
        # Apply floor
        position = max(2, position)
        
        # Round to nearest $0.50
        position = round(position * 2) / 2
        
        return position
    
    def update_after_trade(self, profit, was_win):
        """Update stats after trade"""
        
        self.total_trades += 1
        if was_win:
            self.winning_trades += 1
        
        self.total_profit += profit
        self.current_capital += profit
        
        # Check if cap changed
        new_cap = self.get_position_cap()
        
        # Log cap changes
        if not self.cap_history or self.cap_history[-1]['cap'] != new_cap:
            self.cap_history.append({
                'timestamp': datetime.now().isoformat(),
                'day': self.get_days_elapsed(),
                'capital': self.current_capital,
                'cap': new_cap,
                'trades': self.total_trades,
                'win_rate': self.get_win_rate()
            })
            
            print(f"\n{'='*80}")
            print(f"📈 POSITION CAP INCREASED!")
            print(f"{'='*80}")
            print(f"Day {self.get_days_elapsed()}")
            print(f"Capital: ${self.current_capital:.2f}")
            print(f"New cap: ${new_cap}")
            print(f"Win rate: {self.get_win_rate()*100:.1f}%")
            print(f"{'='*80}\n")
    
    def get_projection(self, days_ahead=90):
        """
        Project capital and position sizes for next N days
        
        Based on current performance
        """
        
        if self.total_trades < 10:
            return None  # Not enough data
        
        # Current metrics
        trades_per_day = self.total_trades / max(1, self.get_days_elapsed())
        avg_profit_per_trade = self.total_profit / self.total_trades if self.total_trades > 0 else 0
        win_rate = self.get_win_rate()
        
        # Project forward
        projections = []
        projected_capital = self.current_capital
        
        for day in range(1, days_ahead + 1):
            # Estimate trades for this day
            trades_today = int(trades_per_day)
            
            # Estimate profit
            daily_profit = trades_today * avg_profit_per_trade
            projected_capital += daily_profit
            
            # Calculate what cap would be
            # Simulate the cap logic
            if projected_capital >= 50000:
                projected_cap = 5000
            elif projected_capital >= 25000:
                projected_cap = 3000
            elif projected_capital >= 15000:
                projected_cap = 2000
            elif projected_capital >= 10000:
                projected_cap = 1500
            elif projected_capital >= 5000:
                projected_cap = 800
            elif projected_capital >= 2500:
                projected_cap = 400
            elif projected_capital >= 1000:
                projected_cap = 200
            elif projected_capital >= 500:
                projected_cap = 100
            elif projected_capital >= 250:
                projected_cap = 50
            else:
                projected_cap = 25
            
            # Apply time limit
            current_day = self.get_days_elapsed() + day
            if current_day < 7:
                time_cap = 25
            elif current_day < 14:
                time_cap = 50
            elif current_day < 21:
                time_cap = 100
            elif current_day < 30:
                time_cap = 200
            elif current_day < 45:
                time_cap = 400
            elif current_day < 60:
                time_cap = 800
            elif current_day < 75:
                time_cap = 1500
            else:
                time_cap = 5000
            
            projected_cap = min(projected_cap, time_cap)
            projected_cap = min(projected_cap, projected_capital * 0.20)
            
            projections.append({
                'day': current_day,
                'capital': projected_capital,
                'cap': projected_cap,
                'daily_profit': daily_profit
            })
        
        return projections
    
    def print_90_day_plan(self):
        """Print complete 90-day scaling plan"""
        
        print("\n" + "="*80)
        print("📊 90-DAY ADAPTIVE POSITION SIZING PLAN")
        print("="*80)
        print()
        
        milestones = [
            {"days": "1-7",    "capital": "$100-250",    "cap": "$25",    "position_98": "$10"},
            {"days": "8-14",   "capital": "$250-500",    "cap": "$50",    "position_98": "$20-50"},
            {"days": "15-21",  "capital": "$500-1,000",  "cap": "$100",   "position_98": "$50-100"},
            {"days": "22-30",  "capital": "$1k-2.5k",    "cap": "$200",   "position_98": "$100-200"},
            {"days": "31-45",  "capital": "$2.5k-5k",    "cap": "$400",   "position_98": "$200-400"},
            {"days": "46-60",  "capital": "$5k-10k",     "cap": "$800",   "position_98": "$400-800"},
            {"days": "61-75",  "capital": "$10k-15k",    "cap": "$1,500", "position_98": "$800-1,500"},
            {"days": "76-90",  "capital": "$15k-50k+",   "cap": "$3,000", "position_98": "$1,500-3,000"},
        ]
        
        print("PHASE          CAPITAL         MAX CAP    98% CONF POSITION")
        print("-" * 80)
        for m in milestones:
            print(f"{m['days']:12s}   {m['capital']:14s}  {m['cap']:9s}  {m['position_98']}")
        
        print()
        print("KEY FEATURES:")
        print("  ✅ Caps increase automatically as capital grows")
        print("  ✅ Time-based safety limits prevent over-leveraging")
        print("  ✅ Win rate adjustments protect during bad streaks")
        print("  ✅ Never more than 20% of capital in single trade")
        print("  ✅ Positions scale with confidence (90%-98%)")
        print()
        print("="*80 + "\n")
    
    def export_cap_history(self, filename='cap_history.json'):
        """Export cap changes to file"""
        with open(filename, 'w') as f:
            json.dump(self.cap_history, f, indent=2)


def simulate_90_day_growth():
    """
    Simulate 90 days of trading with adaptive position sizing
    Shows how caps and positions grow over time
    """
    
    print("\n" + "="*80)
    print("🎮 90-DAY GROWTH SIMULATION")
    print("="*80)
    print()
    print("Assumptions:")
    print("  - 20 trades/day average")
    print("  - 72% win rate")
    print("  - 35% avg return per winning trade")
    print("  - -100% loss on losing trades")
    print()
    print("="*80 + "\n")
    
    sizing = AdaptivePositionSizing(starting_capital=100)
    
    # Track for summary
    weekly_summaries = []
    
    for day in range(1, 91):
        daily_trades = 20
        daily_profit = 0
        
        for trade_num in range(daily_trades):
            # Simulate confidence (weighted toward higher)
            import random
            rand = random.random()
            if rand < 0.15:
                confidence = 98
            elif rand < 0.35:
                confidence = 95
            elif rand < 0.60:
                confidence = 92
            else:
                confidence = 90
            
            # Calculate position
            position = sizing.calculate_position_size(confidence)
            
            # Simulate outcome
            is_win = random.random() < 0.72  # 72% win rate
            
            if is_win:
                profit = position * 0.35  # 35% return
            else:
                profit = -position  # Total loss
            
            daily_profit += profit
            sizing.update_after_trade(profit, is_win)
        
        # Print weekly summary
        if day % 7 == 0:
            week = day // 7
            cap = sizing.get_position_cap()
            win_rate = sizing.get_win_rate()
            
            weekly_summaries.append({
                'week': week,
                'day': day,
                'capital': sizing.current_capital,
                'cap': cap,
                'win_rate': win_rate,
                'total_profit': sizing.total_profit
            })
            
            print(f"📅 WEEK {week} (Day {day})")
            print(f"   Capital: ${sizing.current_capital:,.2f}")
            print(f"   Position cap: ${cap}")
            print(f"   Win rate: {win_rate*100:.1f}%")
            print(f"   Total profit: ${sizing.total_profit:,.2f}")
            print(f"   ROI: {(sizing.current_capital/100 - 1)*100:.1f}%")
            print()
    
    # Final summary
    print("\n" + "="*80)
    print("🎉 90-DAY SIMULATION COMPLETE")
    print("="*80)
    print()
    print(f"Starting capital: $100")
    print(f"Ending capital: ${sizing.current_capital:,.2f}")
    print(f"Total profit: ${sizing.total_profit:,.2f}")
    print(f"ROI: {(sizing.current_capital/100 - 1)*100:.1f}%")
    print()
    print(f"Total trades: {sizing.total_trades:,}")
    print(f"Win rate: {sizing.get_win_rate()*100:.1f}%")
    print(f"Final position cap: ${sizing.get_position_cap()}")
    print()
    
    # Show growth curve
    print("GROWTH CURVE:")
    print("-" * 80)
    print("WEEK    CAPITAL         CAP      WIN RATE    ROI")
    print("-" * 80)
    for w in weekly_summaries:
        roi = (w['capital']/100 - 1)*100
        print(f"{w['week']:2d}      ${w['capital']:11,.2f}   ${w['cap']:5,}    {w['win_rate']*100:5.1f}%      {roi:6.1f}%")
    
    print("="*80 + "\n")
    
    return sizing


if __name__ == "__main__":
    # Show plan
    sizing = AdaptivePositionSizing(100)
    sizing.print_90_day_plan()
    
    # Run simulation
    print("\nRunning 90-day simulation...\n")
    result = simulate_90_day_growth()
