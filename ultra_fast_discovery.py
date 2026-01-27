"""
Ultra-Fast Discovery System
Scans blockchain EVERY MINUTE to catch new whales instantly

Two-tier approach:
1. LIGHT scan every minute (last 200 blocks ~ 5 minutes)
2. DEEP scan every hour (last 50,000 blocks ~ 1 week)

This maximizes opportunity detection while managing costs
"""

import asyncio
from datetime import datetime, timedelta
from collections import defaultdict
import pandas as pd
import json

from whale_analyzer import PolymarketWhaleAnalyzer
from fifteen_minute_analyzer import FifteenMinuteWhaleAnalyzer
import config


class UltraFastDiscovery:
    """
    Scans every minute for new profitable 15-min traders
    
    Perfect for $100 starting capital - need to catch EVERY opportunity
    """
    
    def __init__(self):
        self.analyzer = FifteenMinuteWhaleAnalyzer()
        self.whale_database = {}
        self.monitoring_pool = []
        
        # Two scan intervals
        self.light_scan_interval = 60  # 1 minute
        self.deep_scan_interval = 3600  # 1 hour
        
        # Track what we've seen
        self.last_light_scan_block = 0
        self.last_deep_scan_block = 0
        
        print("⚡ ULTRA-FAST DISCOVERY MODE")
        print(f"   Light scan: Every {self.light_scan_interval} seconds")
        print(f"   Deep scan: Every {self.deep_scan_interval/60:.0f} minutes")
        print(f"   Goal: NEVER miss a hot new whale")
    
    async def run_ultra_fast_discovery(self):
        """
        Main loop with two parallel scan types
        """
        
        print("\n" + "="*80)
        print("⚡ ULTRA-FAST DISCOVERY ACTIVE")
        print("="*80)
        print("\nWith $100 capital, we need MAXIMUM opportunities")
        print("Scanning every minute to catch new whales instantly!\n")
        
        # Initial deep scan
        print("🔍 Initial deep scan...")
        await self.deep_scan()
        
        # Start both loops
        light_task = asyncio.create_task(self.light_scan_loop())
        deep_task = asyncio.create_task(self.deep_scan_loop())
        stats_task = asyncio.create_task(self.print_stats_loop())
        
        try:
            await asyncio.gather(light_task, deep_task, stats_task)
        except KeyboardInterrupt:
            print("\n⚠️  Discovery stopped")
    
    async def light_scan_loop(self):
        """
        LIGHT SCAN: Every minute, scan last ~5 minutes of blocks
        
        This catches:
        - Brand new wallets making their first trades
        - Existing whales making new trades
        - Rapid changes in performance
        """
        
        while True:
            try:
                await asyncio.sleep(self.light_scan_interval)
                
                current_block = self.analyzer.w3.eth.block_number
                
                # Scan last 200 blocks (~5 minutes on Polygon)
                from_block = max(
                    self.last_light_scan_block,
                    current_block - 200
                )
                
                if from_block >= current_block:
                    continue
                
                print(f"\n⚡ Light scan: blocks {from_block} → {current_block}")
                
                # Quick scan
                new_whales = await self.quick_scan(from_block, current_block)
                
                if new_whales:
                    print(f"   🆕 Found {len(new_whales)} new/updated whales")
                    await self.update_pool()
                
                self.last_light_scan_block = current_block
                
            except Exception as e:
                print(f"   ❌ Light scan error: {e}")
                await asyncio.sleep(10)
    
    async def deep_scan_loop(self):
        """
        DEEP SCAN: Every hour, scan last week
        
        This catches:
        - Historical performance
        - Consistency over time
        - Whales we might have missed
        """
        
        while True:
            try:
                await asyncio.sleep(self.deep_scan_interval)
                await self.deep_scan()
                
            except Exception as e:
                print(f"   ❌ Deep scan error: {e}")
                await asyncio.sleep(300)
    
    async def quick_scan(self, from_block, to_block):
        """
        Quick scan of recent blocks
        Focus on speed over completeness
        """
        
        try:
            # Get OrderFilled events
            events = self.analyzer.ctf_exchange.events.OrderFilled.get_logs(
                from_block=from_block,
                to_block=to_block
            )
            
            if not events:
                return []
            
            # Group by trader
            trader_activity = defaultdict(list)
            
            for event in events:
                maker = event['args']['maker']
                taker = event['args']['taker']
                
                trader_activity[maker].append(event)
                trader_activity[taker].append(event)
            
            # Quick analysis
            new_whales = []
            
            for trader, trades in trader_activity.items():
                if len(trades) < 2:  # Need at least 2 trades to analyze
                    continue
                
                # Quick metrics
                trade_count = len(trades)
                
                # Estimate win rate (simplified)
                # In real version, would check resolutions
                estimated_win_rate = 0.65  # Placeholder
                
                # If new or significantly active, add/update
                if trader not in self.whale_database or trade_count >= 5:
                    
                    self.whale_database[trader] = {
                        'address': trader,
                        'last_seen': datetime.now(),
                        'recent_trade_count': trade_count,
                        'estimated_win_rate': estimated_win_rate,
                        'discovery_time': self.whale_database.get(trader, {}).get('discovery_time', datetime.now()),
                        'total_scans_seen': self.whale_database.get(trader, {}).get('total_scans_seen', 0) + 1
                    }
                    
                    new_whales.append(trader)
            
            return new_whales
            
        except Exception as e:
            print(f"      Error in quick scan: {e}")
            return []
    
    async def deep_scan(self):
        """
        Deep scan of last week
        Full analysis with historical data
        """
        
        print("\n" + "="*80)
        print(f"🔍 DEEP SCAN - {datetime.now().strftime('%H:%M:%S')}")
        print("="*80)
        
        # Full analysis
        specialists = self.analyzer.find_fifteen_minute_specialists(
            blocks_to_scan=50000
        )
        
        # Update database
        for whale in specialists:
            address = whale['address']
            
            if address not in self.whale_database:
                self.whale_database[address] = {
                    'discovery_time': datetime.now(),
                    'total_scans_seen': 1
                }
            
            self.whale_database[address].update({
                'address': address,
                'last_deep_scan': datetime.now(),
                'trade_count': whale['trade_count'],
                'estimated_profit': whale['estimated_profit'],
                'estimated_win_rate': whale['estimated_win_rate'],
                'markets_traded': whale['markets_traded'],
                'speed_score': whale['speed_score']
            })
        
        print(f"   ✅ Deep scan complete: {len(self.whale_database)} total whales")
        
        await self.update_pool()
    
    async def update_pool(self):
        """
        Update monitoring pool based on latest data
        
        With $100 capital, we want:
        - Top 20-30 whales (not 50, capital too small)
        - Emphasis on RECENT performance (last hour matters more)
        - Rising stars (new hot hands)
        """
        
        ranked = []
        
        for address, data in self.whale_database.items():
            # Calculate score
            score = 0
            
            # Factor 1: Recent activity (50% weight) - CRITICAL for $100
            last_seen = data.get('last_seen', datetime.min)
            minutes_ago = (datetime.now() - last_seen).total_seconds() / 60
            
            if minutes_ago < 5:
                score += 50  # Active RIGHT NOW
            elif minutes_ago < 60:
                score += 40 * (1 - minutes_ago/60)
            elif minutes_ago < 1440:  # 24 hours
                score += 20 * (1 - minutes_ago/1440)
            
            # Factor 2: Win rate (30% weight)
            win_rate = data.get('estimated_win_rate', 0.5)
            score += (win_rate - 0.5) * 30
            
            # Factor 3: Trade frequency (20% weight)
            recent_count = data.get('recent_trade_count', 0)
            score += min(recent_count * 2, 20)
            
            ranked.append({
                'address': address,
                'score': score,
                **data
            })
        
        # Sort by score
        ranked.sort(key=lambda x: x['score'], reverse=True)
        
        # For $100 capital, monitor top 25 (not 50)
        # Smaller pool = less capital spread = bigger positions
        old_pool = set([w['address'] for w in self.monitoring_pool])
        new_pool = ranked[:25]
        new_addresses = set([w['address'] for w in new_pool])
        
        added = new_addresses - old_pool
        removed = old_pool - new_addresses
        
        self.monitoring_pool = new_pool
        
        if added or removed:
            print(f"\n   🔄 Pool updated: {len(new_pool)} whales")
            if added:
                print(f"      📈 Added {len(added)}")
                for addr in list(added)[:3]:
                    print(f"         {addr[:10]}...")
            if removed:
                print(f"      📉 Removed {len(removed)}")
        
        # Export
        self.export_state()
    
    def export_state(self):
        """Export current state"""
        
        # Monitoring pool
        df = pd.DataFrame(self.monitoring_pool)
        df.to_csv('ultra_fast_pool.csv', index=False)
        
        # Just addresses
        addresses = [w['address'] for w in self.monitoring_pool]
        with open('ultra_fast_addresses.txt', 'w') as f:
            f.write('\n'.join(addresses))
        
        # Stats
        stats = {
            'timestamp': datetime.now().isoformat(),
            'total_whales': len(self.whale_database),
            'monitoring': len(self.monitoring_pool),
            'active_last_5min': sum(1 for w in self.whale_database.values() 
                                    if (datetime.now() - w.get('last_seen', datetime.min)).total_seconds() < 300)
        }
        
        with open('ultra_fast_stats.json', 'w') as f:
            json.dump(stats, f, indent=2)
    
    async def print_stats_loop(self):
        """Print stats every 2 minutes"""
        
        while True:
            await asyncio.sleep(120)  # Every 2 minutes
            
            print("\n" + "-"*80)
            print(f"📊 STATS - {datetime.now().strftime('%H:%M:%S')}")
            print("-"*80)
            print(f"🗄️  Total whales: {len(self.whale_database)}")
            print(f"👀 Monitoring: {len(self.monitoring_pool)}")
            
            active_5min = sum(1 for w in self.whale_database.values() 
                            if (datetime.now() - w.get('last_seen', datetime.min)).total_seconds() < 300)
            print(f"🔥 Active (last 5 min): {active_5min}")
            
            # Show top 5
            print(f"\n🏆 TOP 5:")
            for i, w in enumerate(self.monitoring_pool[:5], 1):
                mins_ago = (datetime.now() - w.get('last_seen', datetime.now())).total_seconds() / 60
                print(f"   #{i} {w['address'][:10]}... (Score: {w['score']:.1f}, {mins_ago:.0f}m ago)")
            
            print("-"*80 + "\n")
    
    def get_monitoring_addresses(self):
        """Get addresses for monitor"""
        return [w['address'] for w in self.monitoring_pool]


async def main():
    """Run ultra-fast discovery"""
    
    print("="*80)
    print("⚡ ULTRA-FAST DISCOVERY SYSTEM")
    print("="*80)
    print()
    print("Optimized for $100 starting capital")
    print()
    print("Strategy:")
    print("  • Scan every MINUTE for new whales")
    print("  • Monitor top 25 (not 50, capital too small)")
    print("  • Prioritize RECENT activity")
    print("  • Catch rising stars instantly")
    print()
    print("Goal: Maximum opportunities with minimal capital")
    print("="*80)
    print()
    
    discovery = UltraFastDiscovery()
    await discovery.run_ultra_fast_discovery()


if __name__ == "__main__":
    asyncio.run(main())
