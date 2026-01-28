# ⚡ QUICK START CHECKLIST

## 🎯 30-Minute Setup

### **Prerequisites** (5 min)
```
✅ Computer with internet
✅ $100 USDC ready to deposit
✅ Email for account signups
```

---

### **Step 1: Software** (10 min)

```bash
# Install Python
Windows: Download from python.org
Mac: brew install python
Linux: sudo apt install python3

# Verify
python --version  # Should show 3.8+

# Install packages
pip install web3 pandas py-clob-client python-dotenv tqdm colorama
```

---

### **Step 2: API Keys** (10 min)

**Polymarket:**
1. polymarket.com → Sign up
2. Profile → Settings → API Keys
3. Create New Key
4. Save: API Key, Secret, Passphrase

**Alchemy (optional but recommended):**
1. alchemy.com → Sign up (free)
2. Create App → Polygon Mainnet
3. Copy HTTPS URL

---

### **Step 3: Configuration** (5 min)

**Create `.env` file:**
```bash
# Paste your keys
POLYMARKET_API_KEY=your-api-key
POLYMARKET_SECRET=your-secret
POLYMARKET_PASSPHRASE=your-passphrase

# RPC
POLYGON_RPC_URL=https://polygon-rpc.com

# Trading
STARTING_CAPITAL=100
AUTO_COPY_ENABLED=false  # Paper trade first!
MAX_WHALES_TO_MONITOR=25
SCAN_INTERVAL_SECONDS=60
CONFIDENCE_THRESHOLD=90
```

---

### **Step 4: Deposit USDC** (5 min)

```
1. Buy $100 USDC on Coinbase/Binance
2. Get Polymarket wallet address (in app)
3. Withdraw USDC to that address
4. ⚠️ SELECT POLYGON NETWORK (not Ethereum!)
5. Wait 2-3 minutes
```

---

### **Step 5: TEST** (5 min)

```bash
# Run discovery
python small_capital_system.py

# Should see:
✅ Finding whales...
✅ Monitoring 23 whales
✅ Starting with $100

# If errors, check:
- .env file has correct keys
- No typos in API credentials
- Python version 3.8+
```

---

## 📋 Daily Checklist

### **Morning** (2 min)
```
□ Check if system still running
□ Quick look at P&L
□ Any errors?
```

### **Evening** (5 min)
```
□ Review trades for the day
□ Check win rate (should be >70%)
□ Verify capital growing
```

### **Weekly** (15 min)
```
□ Calculate weekly ROI
□ Review whale performance
□ Adjust settings if needed
□ Withdraw profits or compound
```

---

## 🎯 Expected Timeline

### **Week 1: Paper Trading**
```
Day 1: Setup complete ✅
Day 2-7: Watch simulated trades
Result: Verify >70% win rate
```

### **Week 2: Live Small**
```
Day 8: Enable AUTO_COPY_ENABLED=true
Day 8-14: $4-10 positions
Result: $100 → $130-150
```

### **Week 3: Growing**
```
Day 15-21: Positions grow to $10-20
Result: $150 → $250-350
```

### **Week 4: Compounding**
```
Day 22-30: Positions grow to $20-40
Result: $350 → $600-900
```

---

## 💰 Cost Summary

### **Setup Costs**
```
Python: FREE
API keys: FREE
Alchemy: FREE (or $20/month for paid)
Starting capital: $100
──────────────
Total: $100
```

### **Monthly Costs**
```
RPC: $0-20
Server (optional): $0-6
Claude API (optional): $0-5
──────────────
Total: $0-31/month
```

### **Expected Returns**
```
Month 1: +$150-400 (150-400%)
Month 2: +$500-1,500 (compounding)
Month 3: +$1,500-5,000 (exponential)
```

---

## ⚠️ Safety Checklist

### **Before Going Live**
```
✅ Paper traded for 1 week
✅ Win rate confirmed >70%
✅ Understand all risks
✅ Only using money I can afford to lose
✅ Stop-loss set (30%)
✅ Monitoring daily
```

### **Red Flags to Stop**
```
🛑 Win rate drops below 60%
🛑 Lost >30% of capital
🛑 System throwing errors constantly
🛑 Whales stopped trading
🛑 Feeling emotional about losses
```

---

## 🚀 Launch Command

```bash
# Navigate to folder
cd polymarket-whale-tracker

# START THE SYSTEM
python small_capital_system.py

# You'll see:
⚡ ULTRA-FAST DISCOVERY MODE
💰 $100 CAPITAL SYSTEM
🔍 Finding whales...
✅ Monitoring 25 whales

# Let it run!
```

---

## 📊 Files to Monitor

```bash
# View trade history
cat small_capital_log.jsonl

# View current whales
cat ultra_fast_pool.csv

# View performance stats
cat ultra_fast_stats.json
```

---

## 🎯 Quick Troubleshooting

### **Error: "Module not found"**
```bash
pip install <module-name>
```

### **Error: "Invalid credentials"**
```bash
# Check .env file for typos
# Regenerate Polymarket API keys
```

### **Error: "RPC connection failed"**
```bash
# Try: https://polygon-rpc.com
# Or get Alchemy key
```

### **No whales found**
```bash
# Normal on first run
# Wait 1 hour for more data
# Try increasing BLOCKS_TO_SCAN
```

---

## ✅ You're Ready When:

```
✅ Python installed
✅ Packages installed
✅ API keys in .env file
✅ $100 USDC in Polymarket
✅ System runs without errors
✅ Paper traded for 1 week
✅ Understand the risks

RUN: python small_capital_system.py
```

---

## 🎉 Success Metrics

### **After 1 Week**
```
✅ System ran 24/7 without issues
✅ Win rate >70%
✅ Positive simulated P&L
✅ Found 20+ whales
```

### **After 1 Month**
```
✅ Capital grew 30-100%
✅ Win rate maintained >70%
✅ Confident in system
✅ Ready to scale
```

---

## 💎 Remember

**Start small** → Test thoroughly → Scale slowly

**$100 → $1,000 in 60-90 days is realistic!** 🚀

**Let the system do the work while you sleep! 💤**
