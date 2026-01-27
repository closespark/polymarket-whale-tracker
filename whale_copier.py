"""
Whale Trade Copier
Automatically copies trades from profitable whales
"""

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType, ApiCreds
import anthropic
import json
from datetime import datetime
from colorama import Fore, Style, init

import config

init(autoreset=True)


class WhaleCopier:
    """Automatically copy whale trades on Polymarket"""
    
    def __init__(self):
        """Initialize Polymarket API client"""

        # Create API credentials
        creds = ApiCreds(
            api_key=config.POLYMARKET_API_KEY,
            api_secret=config.POLYMARKET_SECRET,
            api_passphrase=config.POLYMARKET_PASSPHRASE
        )

        # Initialize Polymarket CLOB client with proxy wallet configuration
        # signature_type: 0=EOA, 1=POLY_PROXY (Magic/email), 2=GNOSIS_SAFE
        self.client = ClobClient(
            host=config.POLYMARKET_CLOB_API,
            key=config.PRIVATE_KEY,
            chain_id=137,  # Polygon mainnet
            signature_type=config.SIGNATURE_TYPE,
            funder=config.FUNDER_ADDRESS,
            creds=creds
        )
        
        # Initialize Claude for trade analysis
        if config.ANTHROPIC_API_KEY:
            self.claude = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        else:
            self.claude = None
            print(f"{Fore.YELLOW}⚠️  No Anthropic API key - AI analysis disabled")
        
        print(f"{Fore.GREEN}✅ Whale Copier initialized")
        print(f"   Auto-copy: {'ENABLED' if config.AUTO_COPY_ENABLED else 'DISABLED'}")
        print(f"   Max copy size: ${config.MAX_COPY_SIZE_USD}")
        print(f"   Confidence threshold: {config.CONFIDENCE_THRESHOLD}%")
    
    async def process_whale_trade(self, trade_data):
        """
        Process a whale trade and decide whether to copy
        
        Args:
            trade_data: Dict with whale trade information
        
        Returns:
            Dict with copy result
        """
        
        print(f"\n{Fore.CYAN}📊 Analyzing whale trade...")
        
        # Step 1: Score the trade
        score = await self.score_trade(trade_data)
        
        print(f"{Fore.CYAN}   Confidence Score: {score['confidence']:.1f}%")
        print(f"{Fore.CYAN}   Recommendation: {score['recommendation']}")
        
        # Step 2: Decide whether to copy
        should_copy = (
            config.AUTO_COPY_ENABLED and
            score['confidence'] >= config.CONFIDENCE_THRESHOLD and
            trade_data['usdc_value'] <= config.MAX_COPY_SIZE_USD
        )
        
        if should_copy:
            # Step 3: Execute copy trade
            result = await self.copy_trade(trade_data, score)
            return result
        else:
            reasons = []
            if not config.AUTO_COPY_ENABLED:
                reasons.append("Auto-copy disabled")
            if score['confidence'] < config.CONFIDENCE_THRESHOLD:
                reasons.append(f"Confidence too low ({score['confidence']:.1f}% < {config.CONFIDENCE_THRESHOLD}%)")
            if trade_data['usdc_value'] > config.MAX_COPY_SIZE_USD:
                reasons.append(f"Trade too large (${trade_data['usdc_value']:.2f} > ${config.MAX_COPY_SIZE_USD})")
            
            print(f"{Fore.YELLOW}⏸️  NOT copying trade:")
            for reason in reasons:
                print(f"{Fore.YELLOW}   - {reason}")
            
            return {
                'copied': False,
                'reasons': reasons,
                'score': score
            }
    
    async def score_trade(self, trade_data):
        """
        Score whale trade using AI and historical data
        
        Returns:
            Dict with confidence score and recommendation
        """
        
        # Base score from whale's historical performance
        # (In production, would query database for whale stats)
        base_score = 70.0
        
        # Use Claude to analyze if available
        if self.claude and trade_data.get('market_question'):
            ai_analysis = await self._analyze_with_claude(trade_data)
            base_score = (base_score + ai_analysis['score']) / 2
        
        # Adjust based on trade characteristics
        
        # 1. Trade size (larger = higher conviction)
        if trade_data['usdc_value'] > 500:
            base_score += 10
        elif trade_data['usdc_value'] < 100:
            base_score -= 5
        
        # 2. Price level (extreme prices = higher conviction)
        if trade_data['price'] > 0.8 or trade_data['price'] < 0.2:
            base_score += 5
        
        # Cap score at 100
        confidence = min(base_score, 100.0)
        
        # Determine recommendation
        if confidence >= 85:
            recommendation = "STRONG COPY"
        elif confidence >= 70:
            recommendation = "COPY"
        elif confidence >= 50:
            recommendation = "MONITOR"
        else:
            recommendation = "PASS"
        
        return {
            'confidence': confidence,
            'recommendation': recommendation,
            'factors': {
                'base_score': base_score,
                'trade_size': trade_data['usdc_value'],
                'price': trade_data['price']
            }
        }
    
    async def _analyze_with_claude(self, trade_data):
        """Use Claude to analyze the trade"""
        
        prompt = f"""Analyze this Polymarket whale trade:

Market: {trade_data['market_question']}
Whale Action: {trade_data['side']} at ${trade_data['price']:.4f}
Amount: ${trade_data['usdc_value']:.2f}

This whale has historically been profitable. Should we copy this trade?

Consider:
1. Market question quality
2. Price level (is it reasonable?)
3. Side taken (BUY or SELL)
4. Amount invested

Return JSON only:
{{
    "score": 0-100,
    "reasoning": "brief explanation",
    "red_flags": ["any concerns"],
    "should_copy": true/false
}}"""
        
        try:
            response = self.claude.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}]
            )
            
            analysis = json.loads(response.content[0].text)
            return analysis
        
        except Exception as e:
            print(f"{Fore.YELLOW}⚠️  Claude analysis failed: {e}")
            return {'score': 70, 'reasoning': 'AI analysis unavailable'}
    
    async def copy_trade(self, trade_data, score):
        """
        Execute a copy trade on Polymarket
        
        Args:
            trade_data: Original whale trade data
            score: Confidence score for the trade
        
        Returns:
            Dict with execution result
        """
        
        print(f"\n{Fore.GREEN}{'='*80}")
        print(f"{Fore.GREEN}🚀 COPYING WHALE TRADE")
        print(f"{Fore.GREEN}{'='*80}")
        
        # Calculate copy size (scale down based on confidence if needed)
        copy_size = min(
            trade_data['usdc_value'] * (score['confidence'] / 100),
            config.MAX_COPY_SIZE_USD
        )
        
        print(f"{Fore.WHITE}Original trade: ${trade_data['usdc_value']:.2f}")
        print(f"{Fore.WHITE}Copy size: ${copy_size:.2f}")
        print(f"{Fore.WHITE}Market: {trade_data['market_question']}")
        print(f"{Fore.WHITE}Side: {trade_data['side']}")
        print(f"{Fore.WHITE}Price: ${trade_data['price']:.4f}")
        
        try:
            # Create order on Polymarket
            # NOTE: This is simplified - full implementation needs:
            # 1. Get correct token_id for the market
            # 2. Check available balance
            # 3. Set appropriate price slippage
            # 4. Handle order signing
            
            order_args = {
                'token_id': trade_data['token_id'],
                'price': trade_data['price'],
                'size': copy_size / trade_data['price'],  # Convert USD to token amount
                'side': trade_data['side'],
                'fee_rate_bps': 0,  # Polymarket fee structure
                'nonce': 0,  # Would need to get from API
            }
            
            print(f"{Fore.YELLOW}⚠️  DRY RUN - Not executing actual order")
            print(f"{Fore.YELLOW}   (Set AUTO_COPY_ENABLED=true in .env to enable)")
            
            # In production, would execute:
            # order = self.client.create_order(order_args)
            
            result = {
                'copied': True,
                'dry_run': not config.AUTO_COPY_ENABLED,
                'copy_size': copy_size,
                'order_args': order_args,
                'timestamp': datetime.now(),
                'confidence': score['confidence']
            }
            
            print(f"{Fore.GREEN}✅ Trade copy prepared successfully")
            print(f"{Fore.GREEN}{'='*80}\n")
            
            return result
        
        except Exception as e:
            print(f"{Fore.RED}❌ Failed to copy trade: {e}")
            return {
                'copied': False,
                'error': str(e)
            }
    
    def get_account_balance(self):
        """Get current USDC balance on Polymarket"""
        
        try:
            # Would query balance from API
            # balance = self.client.get_balance()
            balance = 0  # Placeholder
            return balance
        except Exception as e:
            print(f"{Fore.RED}Error getting balance: {e}")
            return 0


async def test_copier():
    """Test the whale copier with example trade"""
    
    copier = WhaleCopier()
    
    # Example whale trade
    example_trade = {
        'whale_address': '0x1234...5678',
        'side': 'BUY',
        'token_id': '123456',
        'amount': 1000,
        'price': 0.62,
        'usdc_value': 620,
        'market_question': 'Will Bitcoin reach $100k in 2024?',
        'market_id': 'btc-100k-2024',
        'timestamp': datetime.now()
    }
    
    result = await copier.process_whale_trade(example_trade)
    
    print(f"\n{Fore.CYAN}Result:")
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_copier())
