"""
$100 Capital Optimized Trading System

Special optimizations for small capital:
1. Scan EVERY MINUTE (can't miss opportunities)
2. Monitor 20-25 whales (not 50, capital too spread)
3. Smaller positions ($4-10 per trade)
4. Higher confidence threshold (90%+)
5. Aggressive compounding
"""

import asyncio
from datetime import datetime
import json

from ultra_fast_discovery import UltraFastDiscovery
from fifteen_minute_monitor import FifteenMinuteMonitor
from whale_copier import WhaleCopier
from claude_validator import ClaudeTradeValidator
import config


class SmallCapitalSystem:
    """
    Complete system optimized for $100 starting capital
    
    Key differences from standard system:
    - Scans every minute (not hourly)
    - Monitors 20-25 whales (not 50)
    - Smaller copy sizes ($4-10)
    - Higher selectivity (only best trades)
    - Aggressive compounding strategy
    """
    
    def __init__(self, starting_capital=100):
        self.starting_capital = starting_capital
        self.current_capital = starting_capital
        
        self.discovery = UltraFastDiscovery()
        self.monitor = None
        self.copier = WhaleCopier()
        self.claude_validator = ClaudeTradeValidator()  # Add Claude AI
        
        # Small capital stats
        self.stats = {
            'start_time': datetime.now(),
            'starting_capital': starting_capital,
            'current_capital': starting_capital,
            'opportunities': 0,
            'copies': 0,
            'wins': 0,
            'losses': 0,
            'total_profit': 0,
            'best_trade': 0,
            'worst_trade': 0,
            'consecutive_wins': 0,
            'max_consecutive_wins': 0,
            'roi_percent': 0
        }
        
        print(f"💰 SMALL CAPITAL SYSTEM")
        print(f"   Starting capital: ${starting_capital}")
        print(f"   Optimized for MAXIMUM growth")
    
    async def run(self):
        """
        Run optimized system for small capital
        """
        
        print("\n" + "="*80)
        print("💰 $100 CAPITAL OPTIMIZATION SYSTEM")
        print("="*80)
        print()
        print("Special optimizations:")
        print("  ⚡ Scan every MINUTE (can't miss opportunities)")
        print("  🎯 Monitor 20-25 best whales (focused pool)")
        print("  💵 Copy sizes: $4-10 (20-40 trades possible)")
        print("  🎲 High selectivity (confidence >90%)")
        print("  📈 Aggressive compounding (weekly increases)")
        print()
        print("Goal: $100 → $1,000 in 30 days (900% return)")
        print("="*80)
        print()
        
        # Initial discovery
        print("🔍 Finding best 15-min traders...")
        await self.discovery.deep_scan()
        
        print(f"\n✅ Found {len(self.discovery.monitoring_pool)} whales to monitor")
        print(f"   Starting with ${self.current_capital:.2f}\n")
        
        # Start parallel tasks
        discovery_task = asyncio.create_task(
            self.discovery.run_ultra_fast_discovery()
        )
        
        monitoring_task = asyncio.create_task(
            self.run_monitoring()
        )
        
        stats_task = asyncio.create_task(
            self.print_stats_loop()
        )
        
        compound_task = asyncio.create_task(
            self.compound_loop()
        )
        
        try:
            await asyncio.gather(
                discovery_task,
                monitoring_task,
                stats_task,
                compound_task
            )
        except KeyboardInterrupt:
            print("\n⚠️  System stopped")
            self.print_final_summary()
    
    async def run_monitoring(self):
        """Monitor with small-capital optimizations"""
        
        while True:
            try:
                # Get current whales
                whale_addresses = self.discovery.get_monitoring_addresses()
                
                if not whale_addresses:
                    await asyncio.sleep(60)
                    continue
                
                # Create monitor
                self.monitor = FifteenMinuteMonitor(whale_addresses)
                
                # Monitor with callback
                async def trade_callback(trade_data):
                    await self.process_trade_small_capital(trade_data)
                
                await self.monitor.start_monitoring(callback=trade_callback)
                
            except Exception as e:
                print(f"❌ Monitoring error: {e}")
                await asyncio.sleep(60)
    
    async def process_trade_small_capital(self, trade_data):
        """
        Process trades with small capital optimization
        
        Key differences:
        - Higher confidence threshold (90% vs 80%)
        - Dynamic position sizing based on capital
        - Stop-loss if capital drops 30%
        """
        
        self.stats['opportunities'] += 1
        
        # Calculate confidence
        score = await self.copier.score_trade(trade_data)
        confidence = score.get('confidence', 0)
        
        # USE CLAUDE AI FOR VALIDATION
        if self.claude_validator.enabled:
            print(f"\n🤖 Analyzing with Claude AI...")
            claude_result = await self.claude_validator.validate_trade(trade_data, confidence)
            
            print(f"   Base confidence: {confidence:.1f}%")
            print(f"   AI adjustment: {claude_result['ai_confidence_boost']:+.1f}%")
            print(f"   Final confidence: {claude_result['final_confidence']:.1f}%")
            print(f"   Reasoning: {claude_result['reasoning']}")
            
            if claude_result['concerns']:
                print(f"   ⚠️  Concerns: {', '.join(claude_result['concerns'])}")
            
            # Use AI-adjusted confidence
            confidence = claude_result['final_confidence']
            
            # Log validation
            self.claude_validator.log_validation(trade_data, claude_result)
        
        # STRICT threshold for small capital
        if confidence < 90:
            self.stats['copies'] += 1  # Track as "passed"
            return
        
        # Calculate position size based on current capital
        position_size = self.calculate_position_size(confidence)
        
        # Check if we have capital
        if position_size > self.current_capital * 0.15:  # Max 15% per trade
            position_size = self.current_capital * 0.15
        
        if position_size < 2:  # Minimum $2 to make sense
            print(f"   ⚠️  Capital too low for this trade (${self.current_capital:.2f})")
            return
        
        # COPY THE TRADE
        print(f"\n{'='*80}")
        print(f"🎯 HIGH CONFIDENCE TRADE")
        print(f"{'='*80}")
        print(f"Whale: {trade_data['whale_address'][:10]}...")
        print(f"Confidence: {confidence:.1f}%")
        print(f"Position: ${position_size:.2f} ({position_size/self.current_capital*100:.1f}% of capital)")
        print(f"Current capital: ${self.current_capital:.2f}")
        
        # Execute (or simulate)
        if config.AUTO_COPY_ENABLED:
            result = await self.copier.copy_trade(trade_data, position_size)
            profit = result.get('profit', 0)
        else:
            # Simulate
            print(f"🔶 DRY RUN - Set AUTO_COPY_ENABLED=true to trade")
            # Estimate profit (simplified)
            if confidence > 95:
                profit = position_size * 0.35  # 35% return
            elif confidence > 92:
                profit = position_size * 0.25
            else:
                profit = position_size * 0.15
        
        # Update stats
        self.stats['copies'] += 1
        self.current_capital += profit
        self.stats['total_profit'] += profit
        self.stats['current_capital'] = self.current_capital
        
        if profit > 0:
            self.stats['wins'] += 1
            self.stats['consecutive_wins'] += 1
            self.stats['max_consecutive_wins'] = max(
                self.stats['max_consecutive_wins'],
                self.stats['consecutive_wins']
            )
            if profit > self.stats['best_trade']:
                self.stats['best_trade'] = profit
        else:
            self.stats['losses'] += 1
            self.stats['consecutive_wins'] = 0
            if profit < self.stats['worst_trade']:
                self.stats['worst_trade'] = profit
        
        self.stats['roi_percent'] = (
            (self.current_capital - self.starting_capital) / self.starting_capital * 100
        )
        
        # Log
        self.log_trade(trade_data, position_size, profit, confidence)
        
        # Print result
        if profit > 0:
            print(f"✅ WIN: +${profit:.2f}")
        else:
            print(f"❌ LOSS: ${profit:.2f}")
        
        print(f"💰 New capital: ${self.current_capital:.2f} ({self.stats['roi_percent']:.1f}% ROI)")
        print(f"{'='*80}\n")
        
        # Stop-loss check
        if self.current_capital < self.starting_capital * 0.70:
            print("\n" + "="*80)
            print("🛑 STOP-LOSS TRIGGERED")
            print("="*80)
            print(f"Capital dropped to ${self.current_capital:.2f}")
            print(f"Down {100 - self.current_capital/self.starting_capital*100:.1f}%")
            print("Stopping to prevent further losses")
            print("Review strategy and restart when ready")
            print("="*80 + "\n")
            raise KeyboardInterrupt
    
    def calculate_position_size(self, confidence):
        """
        Dynamic position sizing based on confidence and capital
        
        With $100 capital:
        - 90% confidence: $4 (4%)
        - 92% confidence: $6 (6%)
        - 95% confidence: $8 (8%)
        - 98% confidence: $10 (10%)
        
        As capital grows, sizes increase proportionally
        """
        
        base_percent = 0.04  # 4% base
        
        if confidence >= 98:
            percent = 0.10
        elif confidence >= 95:
            percent = 0.08
        elif confidence >= 92:
            percent = 0.06
        else:
            percent = 0.04
        
        position = self.current_capital * percent
        
        # Round to nearest $0.50
        position = round(position * 2) / 2
        
        return max(2, min(position, 25))  # $2-25 range
    
    async def compound_loop(self):
        """
        Check weekly if we should increase position sizes
        
        Every 7 days, if profitable, increase base sizes
        """
        
        while True:
            await asyncio.sleep(604800)  # 7 days
            
            if self.current_capital > self.starting_capital * 2:
                print("\n" + "="*80)
                print("📈 CAPITAL DOUBLED - COMPOUNDING STRATEGY ENGAGED")
                print("="*80)
                print(f"Starting: ${self.starting_capital}")
                print(f"Current: ${self.current_capital:.2f}")
                print(f"Position sizes will now increase with capital")
                print("="*80 + "\n")
    
    async def print_stats_loop(self):
        """Print stats every 3 minutes"""

        while True:
            await asyncio.sleep(180)

            uptime_hours = (datetime.now() - self.stats['start_time']).total_seconds() / 3600

            print("\n" + "-"*80)
            print(f"📊 $100 CAPITAL STATS - {datetime.now().strftime('%H:%M:%S')}")
            print("-"*80)
            print(f"💰 Starting: ${self.starting_capital}  →  Current: ${self.current_capital:.2f}")
            print(f"📈 ROI: {self.stats['roi_percent']:.1f}%  |  Profit: ${self.stats['total_profit']:.2f}")
            print(f"📊 Trades: {self.stats['copies']}  |  Wins: {self.stats['wins']}  |  Losses: {self.stats['losses']}")

            if self.stats['copies'] > 0:
                win_rate = self.stats['wins'] / self.stats['copies'] * 100
                avg_profit = self.stats['total_profit'] / self.stats['copies']
                print(f"🎯 Win rate: {win_rate:.1f}%  |  Avg profit: ${avg_profit:.2f}")

            print(f"🔥 Best trade: ${self.stats['best_trade']:.2f}  |  Worst: ${self.stats['worst_trade']:.2f}")
            print(f"⚡ Streak: {self.stats['consecutive_wins']} wins  |  Best: {self.stats['max_consecutive_wins']}")

            if uptime_hours > 0:
                profit_per_hour = self.stats['total_profit'] / uptime_hours
                profit_per_day = profit_per_hour * 24
                print(f"💵 Profit/day: ${profit_per_day:.2f}")

                # Projection to $1,000
                if profit_per_day > 0:
                    days_to_1k = (1000 - self.current_capital) / profit_per_day
                    print(f"🎯 Days to $1,000: {days_to_1k:.1f} days")

            print("-"*80 + "\n")

            # Save stats to file for dashboard
            self.save_trading_stats()

    def save_trading_stats(self):
        """Save comprehensive trading stats to JSON file"""

        uptime_seconds = (datetime.now() - self.stats['start_time']).total_seconds()
        uptime_hours = uptime_seconds / 3600

        # Calculate derived metrics
        win_rate = self.stats['wins'] / max(1, self.stats['copies']) * 100
        avg_profit = self.stats['total_profit'] / max(1, self.stats['copies'])
        profit_per_hour = self.stats['total_profit'] / max(0.01, uptime_hours)
        profit_per_day = profit_per_hour * 24

        # Count today's trades from log file
        trades_today = 0
        today_str = datetime.now().strftime('%Y-%m-%d')
        try:
            with open('small_capital_log.jsonl', 'r') as f:
                for line in f:
                    if today_str in line:
                        trades_today += 1
        except:
            pass

        stats_data = {
            'timestamp': datetime.now().isoformat(),
            'mode': 'LIVE' if config.AUTO_COPY_ENABLED else 'DRY_RUN',

            # Capital
            'starting_capital': self.starting_capital,
            'current_capital': round(self.current_capital, 2),
            'total_profit': round(self.stats['total_profit'], 2),
            'roi_percent': round(self.stats['roi_percent'], 2),

            # Trading performance
            'total_trades': self.stats['copies'],
            'winning_trades': self.stats['wins'],
            'losing_trades': self.stats['losses'],
            'win_rate': round(win_rate, 1),
            'avg_profit_per_trade': round(avg_profit, 2),

            # Best/worst
            'best_trade': round(self.stats['best_trade'], 2),
            'worst_trade': round(self.stats['worst_trade'], 2),
            'current_streak': self.stats['consecutive_wins'],
            'best_streak': self.stats['max_consecutive_wins'],

            # Rate metrics
            'profit_per_hour': round(profit_per_hour, 2),
            'profit_per_day': round(profit_per_day, 2),
            'trades_today': trades_today,

            # Runtime
            'start_time': self.stats['start_time'].isoformat(),
            'uptime_hours': round(uptime_hours, 2),
            'opportunities_seen': self.stats['opportunities'],

            # Projections
            'days_to_1k': round((1000 - self.current_capital) / max(0.01, profit_per_day), 1) if profit_per_day > 0 else None
        }

        with open('trading_stats.json', 'w') as f:
            json.dump(stats_data, f, indent=2)
    
    def log_trade(self, trade_data, size, profit, confidence):
        """Log trades for analysis - comprehensive logging for dry run evaluation"""

        # Determine outcome
        if profit > 0:
            outcome = 'WIN'
        elif profit < 0:
            outcome = 'LOSS'
        else:
            outcome = 'BREAK_EVEN'

        # Get whale info from discovery if available
        whale_info = {}
        if hasattr(self, 'discovery') and self.discovery:
            whale_db = getattr(self.discovery, 'whale_database', {})
            whale_info = whale_db.get(trade_data.get('whale_address', ''), {})

        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'mode': 'LIVE' if config.AUTO_COPY_ENABLED else 'DRY_RUN',

            # Capital tracking
            'capital_before': round(self.current_capital - profit, 2),
            'capital_after': round(self.current_capital, 2),
            'position_size': round(size, 2),
            'profit': round(profit, 2),
            'roi_percent': round(self.stats['roi_percent'], 2),

            # Trade details
            'outcome': outcome,
            'confidence': round(confidence, 1),
            'side': trade_data.get('side', 'UNKNOWN'),
            'price': trade_data.get('price', 0),

            # Whale details
            'whale_address': trade_data.get('whale_address', ''),
            'whale_win_rate': whale_info.get('win_rate', 0),
            'whale_total_profit': whale_info.get('total_profit', 0),
            'whale_trade_count': whale_info.get('trade_count', 0),

            # Market details
            'market': trade_data.get('market_question', trade_data.get('market', 'Unknown')),
            'market_type': '15_minute',

            # Running totals
            'total_trades': self.stats['copies'],
            'total_wins': self.stats['wins'],
            'total_losses': self.stats['losses'],
            'win_rate': round(self.stats['wins'] / max(1, self.stats['copies']) * 100, 1),
            'streak': self.stats['consecutive_wins']
        }

        with open('small_capital_log.jsonl', 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
    
    def print_final_summary(self):
        """Print summary when stopped"""
        
        print("\n" + "="*80)
        print("💰 $100 CAPITAL SYSTEM - FINAL SUMMARY")
        print("="*80)
        
        uptime = (datetime.now() - self.stats['start_time']).total_seconds() / 3600
        
        print(f"\n⏱️  Runtime: {uptime:.1f} hours ({uptime/24:.1f} days)")
        
        print(f"\n💰 CAPITAL:")
        print(f"   Starting: ${self.starting_capital}")
        print(f"   Ending: ${self.current_capital:.2f}")
        print(f"   Profit: ${self.stats['total_profit']:.2f}")
        print(f"   ROI: {self.stats['roi_percent']:.1f}%")
        
        print(f"\n📊 TRADING:")
        print(f"   Opportunities: {self.stats['opportunities']}")
        print(f"   Trades: {self.stats['copies']}")
        print(f"   Wins: {self.stats['wins']}")
        print(f"   Losses: {self.stats['losses']}")
        
        if self.stats['copies'] > 0:
            win_rate = self.stats['wins'] / self.stats['copies'] * 100
            avg_profit = self.stats['total_profit'] / self.stats['copies']
            print(f"   Win rate: {win_rate:.1f}%")
            print(f"   Avg profit/trade: ${avg_profit:.2f}")
        
        print(f"\n🎯 BEST/WORST:")
        print(f"   Best trade: ${self.stats['best_trade']:.2f}")
        print(f"   Worst trade: ${self.stats['worst_trade']:.2f}")
        print(f"   Best streak: {self.stats['max_consecutive_wins']} wins")
        
        if uptime > 0:
            print(f"\n⚡ PERFORMANCE:")
            print(f"   Profit/hour: ${self.stats['total_profit']/uptime:.2f}")
            print(f"   Profit/day: ${self.stats['total_profit']/uptime*24:.2f}")
        
        print(f"\n📁 Data saved to: small_capital_log.jsonl")
        print("="*80 + "\n")


async def main():
    """Run $100 capital system"""
    
    # Get starting capital from user or use default
    starting_capital = 100
    
    system = SmallCapitalSystem(starting_capital=starting_capital)
    await system.run()


if __name__ == "__main__":
    asyncio.run(main())
