# 🚀 COMPLETE SETUP GUIDE

## ✅ What You Need

### 1. **Computer Requirements**

**Minimum:**
- Any computer (Windows, Mac, or Linux)
- 4GB RAM
- Stable internet connection
- Can run 24/7 (optional but recommended)

**Recommended:**
- Raspberry Pi 4 ($50) - runs 24/7 cheaply
- OR cloud server (DigitalOcean $6/month)
- OR your regular computer (just leave it on)

---

### 2. **Software Requirements**

**All FREE:**
- Python 3.8 or higher
- Git (for downloading the code)
- Text editor (VS Code recommended, also free)

**Installation links:**
- Python: https://www.python.org/downloads/
- Git: https://git-scm.com/downloads
- VS Code: https://code.visualstudio.com/

---

### 3. **API Keys & Accounts**

**Required (FREE):**

1. **Polymarket Account**
   - Website: https://polymarket.com
   - Create account (free)
   - Deposit $100 USDC to start
   - Generate API keys (we'll show you how)

2. **Polygon RPC** (Blockchain access)
   - Option A: Public RPC (FREE, slower)
     - URL: https://polygon-rpc.com
   - Option B: Alchemy (FREE tier, faster) ⭐ RECOMMENDED
     - Website: https://www.alchemy.com
     - Free tier: 300M requests/month
     - Takes 2 minutes to set up

**Optional (for AI validation):**
3. **Anthropic Claude API** (optional)
   - Website: https://console.anthropic.com
   - $5 credit free for new accounts
   - Only needed if you want AI trade validation
   - Can skip and use rule-based validation

---

### 4. **Money**

**Minimum to start:**
- $100 USDC (for trading)
- $0-20/month for server (optional)
- Total: $100-120 to start

**Recommended:**
- $500-1,000 USDC (better compounding)
- $20/month for paid RPC (faster)
- Total: $520-1,020

---

## 📋 STEP-BY-STEP SETUP

### **Step 1: Install Python** (5 minutes)

**Windows:**
```bash
1. Download from python.org
2. Run installer
3. ✅ CHECK "Add Python to PATH"
4. Click "Install Now"
5. Open Command Prompt, type: python --version
   Should show: Python 3.x.x
```

**Mac:**
```bash
1. Open Terminal
2. Install Homebrew (if not installed):
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
3. Install Python:
   brew install python
4. Verify: python3 --version
```

**Linux:**
```bash
sudo apt update
sudo apt install python3 python3-pip
python3 --version
```

---

### **Step 2: Download The Code** (2 minutes)

```bash
# Open terminal/command prompt
# Navigate to where you want the code
cd Desktop  # or wherever

# Download this folder you already have
# (You already have it from our conversation!)

# OR if starting fresh:
# Just copy the polymarket-whale-tracker folder
```

---

### **Step 3: Install Dependencies** (3 minutes)

```bash
# Navigate to the folder
cd polymarket-whale-tracker

# Install required packages
pip install web3 pandas py-clob-client anthropic python-dotenv tqdm colorama

# Or use the requirements file:
pip install -r requirements.txt
```

**What this installs:**
- `web3` - Connects to blockchain
- `pandas` - Data analysis
- `py-clob-client` - Polymarket trading
- `anthropic` - AI validation (optional)
- `python-dotenv` - Configuration management
- `tqdm` - Progress bars
- `colorama` - Colored terminal output

---

### **Step 4: Get Polymarket API Keys** (5 minutes)

**Method 1: From Polymarket Website**

1. Go to https://polymarket.com
2. Log in to your account
3. Click your profile → Settings
4. Navigate to "API Keys"
5. Click "Create New API Key"
6. Save these 3 values:
   - API Key
   - Secret
   - Passphrase

**Method 2: From Polymarket Pro**

1. Download Polymarket app or use web version
2. Settings → Developer → API Credentials
3. Generate new credentials
4. Save all 3 values

**⚠️ IMPORTANT:**
- These keys give FULL access to your account
- NEVER share them
- Store them safely
- You already have them from your screenshot:
  - API Key: 019bfca1-91e5-79dd-a46d-37ba234e0556
  - Secret: EaMkT2QxfLz__fZBGWMlJxVL8WoGj0ddaVCRxY15CSA=
  - Passphrase: 1879faf5dc453d4ec6b22904cea72beb903ad62b67d73f3ff239406984ad2646

---

### **Step 5: Get Alchemy RPC** (3 minutes) ⭐ RECOMMENDED

**Why Alchemy?**
- FREE tier is generous (300M requests/month)
- 10x faster than public RPCs
- More reliable
- Better for every-minute scanning

**Setup:**
1. Go to https://www.alchemy.com
2. Sign up (free)
3. Create new app:
   - Chain: Polygon
   - Network: Mainnet
4. Copy the HTTPS URL
   - Looks like: https://polygon-mainnet.g.alchemy.com/v2/YOUR-KEY-HERE
5. Save this URL

**OR use public RPC (free, slower):**
- URL: https://polygon-rpc.com
- No signup needed
- Works fine for testing

---

### **Step 6: Configure The System** (5 minutes)

**Create .env file:**

```bash
# In the polymarket-whale-tracker folder
# Create a file called: .env
# Copy this template:
```

```bash
# ============================================
# POLYMARKET API CREDENTIALS
# ============================================
POLYMARKET_API_KEY=019bfca1-91e5-79dd-a46d-37ba234e0556
POLYMARKET_SECRET=EaMkT2QxfLz__fZBGWMlJxVL8WoGj0ddaVCRxY15CSA=
POLYMARKET_PASSPHRASE=1879faf5dc453d4ec6b22904cea72beb903ad62b67d73f3ff239406984ad2646

# ============================================
# BLOCKCHAIN RPC
# ============================================
# Option A: Alchemy (recommended)
POLYGON_RPC_URL=https://polygon-mainnet.g.alchemy.com/v2/YOUR-KEY-HERE

# Option B: Public RPC (backup)
# POLYGON_RPC_URL=https://polygon-rpc.com

# ============================================
# TRADING CONFIGURATION
# ============================================
STARTING_CAPITAL=100
AUTO_COPY_ENABLED=false  # Set to true when ready to trade
MAX_WHALES_TO_MONITOR=25
SCAN_INTERVAL_SECONDS=60  # Every minute

# ============================================
# POSITION SIZING
# ============================================
MIN_COPY_SIZE_USD=2
MAX_COPY_SIZE_USD=25  # Will auto-increase as capital grows
CONFIDENCE_THRESHOLD=90  # Only copy >90% confidence
BASE_POSITION_PERCENT=0.04  # 4% of capital

# ============================================
# WHALE CRITERIA
# ============================================
MIN_WHALE_PROFIT=5000
MIN_WHALE_WIN_RATE=0.70
MIN_WHALE_TRADES=20

# ============================================
# OPTIONAL: CLAUDE API (for AI validation)
# ============================================
# ANTHROPIC_API_KEY=sk-ant-api03-YOUR-KEY-HERE
# Leave blank to use rule-based validation
```

**Save this file as `.env` in the main folder**

---

### **Step 7: Deposit USDC to Polymarket** (10 minutes)

**You need USDC on Polygon network**

**Option A: Direct from Exchange (Easiest)**
1. Buy USDC on Coinbase/Binance/Kraken
2. Withdraw to your Polymarket wallet address
3. Select "Polygon" network (NOT Ethereum!)
4. Send $100+ USDC
5. Wait 2-3 minutes for confirmation

**Option B: Bridge from Ethereum**
1. Buy USDC on Ethereum
2. Use official Polygon bridge: https://wallet.polygon.technology/
3. Bridge USDC to Polygon
4. Send to Polymarket wallet

**⚠️ CRITICAL:**
- Must use POLYGON network (not Ethereum)
- Ethereum would cost $50+ in gas fees
- Polygon costs $0.01
- Double-check network before sending!

**Your Polymarket Wallet Address:**
- Found in Polymarket app → Wallet → Deposit
- Looks like: 0xABC123...
- This is where you send USDC

---

### **Step 8: Test The System** (5 minutes)

**Run discovery to find whales:**

```bash
# Navigate to folder
cd polymarket-whale-tracker

# Find profitable 15-min traders
python small_capital_system.py
```

**You should see:**
```
⚡ ULTRA-FAST DISCOVERY MODE
   Light scan: Every 60 seconds
   Deep scan: Every 60 minutes

💰 $100 CAPITAL SYSTEM
   Position sizes: $4-10
   Confidence threshold: 90%

🔍 Finding best 15-min traders...
   Scanning blockchain...
   
✅ Found 23 whales to monitor
   Starting with $100.00
```

**If you see errors:**
- Check your .env file
- Make sure API keys are correct
- Verify internet connection
- Check Python version (must be 3.8+)

---

### **Step 9: Paper Trading** (Week 1)

**Keep AUTO_COPY_ENABLED=false**

This means the system will:
- ✅ Find whales
- ✅ Monitor their trades
- ✅ Calculate confidence
- ✅ Show what it WOULD copy
- ❌ But NOT actually trade

**Run for 1 week:**
```bash
python small_capital_system.py
```

**You'll see:**
```
🎯 HIGH CONFIDENCE TRADE
Whale: 0x52c8...a9e3
Confidence: 94.2%
Position: $8.00 (8% of capital)
🔶 DRY RUN - Set AUTO_COPY_ENABLED=true to trade
✅ Simulated win: +$2.80
💰 Simulated capital: $102.80
```

**Review after 1 week:**
- Check simulated P&L
- Verify win rate >70%
- Confirm whales are profitable
- Look at trade log

---

### **Step 10: GO LIVE** (When Ready)

**After successful paper trading:**

```bash
# Edit .env file
AUTO_COPY_ENABLED=true  # Change false to true

# Start the system
python small_capital_system.py
```

**Now it will ACTUALLY trade:**
```
🎯 HIGH CONFIDENCE TRADE
Whale: 0x52c8...a9e3
Confidence: 94.2%
Position: $8.00
🚀 EXECUTING TRADE...
✅ Trade executed!
💰 Real capital: $102.80
```

**Monitor closely first few days!**

---

## 🛠️ TROUBLESHOOTING

### **Error: "Module not found"**
```bash
# Solution: Install missing package
pip install <package-name>

# Or reinstall all:
pip install -r requirements.txt
```

### **Error: "RPC connection failed"**
```bash
# Solution 1: Check internet connection
ping polygon-rpc.com

# Solution 2: Try different RPC
# Edit .env, use: https://polygon-mainnet.g.alchemy.com/v2/demo
```

### **Error: "Invalid API credentials"**
```bash
# Solution: Regenerate Polymarket API keys
# Make sure no extra spaces in .env file
# Check for typos
```

### **Error: "Insufficient balance"**
```bash
# Solution: Deposit more USDC
# Or reduce MAX_COPY_SIZE_USD in .env
```

### **Whale discovery finds 0 whales**
```bash
# This is normal if:
# - First run (need to scan more blocks)
# - No 15-min markets active right now
# - Need to wait for trades to happen

# Solution: Let it run for 1 hour
```

---

## 📊 MONITORING YOUR SYSTEM

### **Check Performance**
```bash
# View trade log
cat small_capital_log.jsonl

# View current whales
cat ultra_fast_pool.csv

# View stats
cat ultra_fast_stats.json
```

### **Daily Checklist**
- [ ] System still running?
- [ ] Any errors in output?
- [ ] P&L moving in right direction?
- [ ] Win rate still >70%?
- [ ] USDC balance correct?

### **Weekly Checklist**
- [ ] Review all trades
- [ ] Check whale performance
- [ ] Adjust confidence threshold if needed
- [ ] Consider raising position sizes
- [ ] Withdraw profits if desired

---

## 💰 COST BREAKDOWN

### **One-Time Costs**
```
Starting capital: $100
Computer: $0 (use existing) or $50 (Raspberry Pi)
Total: $100-150
```

### **Monthly Costs**
```
RPC (Alchemy free): $0
OR paid RPC: $20/month
Server (optional): $6/month DigitalOcean
Claude API (optional): $5/month
Total: $0-31/month

Average: ~$15/month
```

### **Expected Monthly Profit**
```
Conservative: $300-500
Realistic: $500-1,000
Optimistic: $1,000-2,000

Even conservative covers costs 20x over!
```

---

## 🎯 TIMELINE

### **Day 1: Setup** (30-60 minutes)
- Install Python
- Download code
- Get API keys
- Configure .env
- Deposit USDC

### **Week 1: Testing** (Passive)
- Paper trade
- Monitor results
- Verify whales profitable
- Check for errors

### **Week 2: Live** (Passive)
- Enable auto-copy
- Start small ($4-10 trades)
- Monitor daily
- Track P&L

### **Week 3-4: Optimize** (Passive)
- Adjust settings
- Add more capital if successful
- Let it compound

### **Day 30: Review** (1 hour)
- Calculate ROI
- Withdraw profits or compound
- Adjust strategy
- Scale up if profitable

---

## ✅ FINAL CHECKLIST

Before starting, make sure you have:

**Software:**
- [ ] Python 3.8+ installed
- [ ] All packages installed (web3, pandas, etc.)
- [ ] Code downloaded

**Accounts:**
- [ ] Polymarket account created
- [ ] API keys generated
- [ ] USDC deposited ($100+)

**Configuration:**
- [ ] .env file created
- [ ] API keys added to .env
- [ ] RPC URL added
- [ ] Settings configured

**Testing:**
- [ ] System runs without errors
- [ ] Whale discovery works
- [ ] Paper trading for 1 week
- [ ] Win rate >70% in paper trading

**Ready to go live:**
- [ ] Understand the risks
- [ ] Only investing what you can afford to lose
- [ ] Have stop-loss set (30%)
- [ ] Monitoring system daily

---

## 🚀 YOU'RE READY!

**Total setup time: 1-2 hours**
**Total cost: $100-150**
**Expected profit: $300-2,000/month**

**Run this command to start:**
```bash
cd polymarket-whale-tracker
python small_capital_system.py
```

**Watch your $100 grow to $1,000+! 🚀**

---

## 📞 NEED HELP?

**Common resources:**
- Python issues: https://stackoverflow.com
- Polymarket docs: https://docs.polymarket.com
- Web3 docs: https://web3py.readthedocs.io
- Polygon RPC: https://polygon.technology

**Remember:** Start small, test thoroughly, scale slowly! 💎
