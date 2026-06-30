# Guide: Running on Interactive Brokers (IBKR) Paper Trading

This guide provides step-by-step instructions to configure, run, and monitor our trading system on the Interactive Brokers (IBKR) paper trading platform.

---

## 📋 Prerequisites

Before starting, ensure you have the following installed on your system:
1. **Python 3.11+** with our project dependencies (`ib-insync`, `pandas`, `numpy`, `scikit-learn`, `statsmodels`, `yfinance`, `streamlit`, `plotly`).
2. **Trader Workstation (TWS)** or **IB Gateway** installed on your execution machine.
   - [Download IB Gateway / TWS from Interactive Brokers](https://www.interactivebrokers.com/en/trading/ibgateway-stable.php)
   - *Note: IB Gateway is recommended for automated servers as it uses fewer resources and does not have a daily UI restart requirement. TWS is recommended for desktop use where you want a visual trading interface.*

---

## ⚙️ Step 1: Configure IBKR TWS / Gateway for API Access

You must enable API socket connections in TWS or Gateway so the trading system can send orders and fetch account data.

### Option A: If using Trader Workstation (TWS)
1. Launch TWS and log in using your **Paper Trading Account** credentials.
2. In the top menu, navigate to **File** > **Global Configuration** (or **Edit** > **Global Configuration** on macOS).
3. In the left panel, select **API** > **Settings**.
4. Check the following options:
   - [x] **Enable ActiveX and Socket Clients**
   - [x] **Read-Only API** (Ensure this is **UNCHECKED** so the system can submit orders)
5. Locate the **Socket Port** field:
   - For **Paper Trading**, change it to **`7497`** (Standard Live TWS port is `7496`).
6. Under **Trusted IPs**, add `127.0.0.1` if you are running the script on the same machine.
7. Click **Apply** and **OK**.

### Option B: If using IB Gateway
1. Launch IB Gateway and select the **Paper Trading** radio button.
2. Log in using your **Paper Trading Account** credentials.
3. In the menu, go to **Configure** > **Settings** > **API** > **Settings**.
4. Check **Enable ActiveX and Socket Clients**.
5. Ensure the **Socket Port** is set to **`4002`** (Standard Live Gateway port is `4001`).
6. Click **Apply** and **OK**.

---

## 🔌 Step 2: Configure the Trading System Code

By default, the trading system operates in `dry_run=True` (Mock) mode to protect capital. You must configure the execution client to talk to the local API.

### Connection Parameters
Create a configuration block or edit the initialization code in your main runner script to disable the mock layer and specify the appropriate port:

```python
from execution.ibkr_client import IBKRClient
from risk.controls import RiskControls

# 1. Initialize Risk Controls (maintains the kill switch state)
risk_controls = RiskControls(lock_file_path="kill_switch.lock")

# 2. Initialize IBKR Client
# Set dry_run=False to execute real paper orders.
# Use port 7497 for TWS Paper or 4002 for IB Gateway Paper.
client = IBKRClient(
    host='127.0.0.1', 
    port=7497,          # Change to 4002 if using IB Gateway
    client_id=1, 
    dry_run=False       # Set to False for real paper trading!
)

# 3. Connect to TWS/Gateway
if client.connect():
    print("Successfully connected to IBKR paper trading platform.")
else:
    print("Could not connect. Checking if TWS/Gateway is open and API is enabled.")
```

---

## 🏃 Step 3: Step-by-Step Running Instructions

Follow this sequence to launch and operate the trading system safely:

### 1. Pre-Flight Tests
Before running live paper trading, execute the isolated unit tests to ensure all risk engines, bracket orders, and the kill switch state machines are functioning properly on your OS environment:
```powershell
python -m unittest discover -s tests
```
Ensure all tests report `OK`.

### 2. Run the Streamlit Dashboard (Live Control Panel)
Launch the visual control panel to monitor live equity, check active positions, view executions, track orders, and keep the Manual Emergency Kill Switch accessible:
```powershell
python -m streamlit run dashboard/streamlit_app.py
```
Open the local URL (typically `http://localhost:8501`) in your browser.

**Dashboard Live Settings**:
- In the **left sidebar**, select **Live Paper Trading (TWS / Gateway)**.
- Set the **Host** (default: `127.0.0.1`) and **Port** (e.g. `4002` for Gateway, `7497` for TWS).
- Check **Auto-refresh** to pull socket updates every 5 seconds.
- You can now visually track:
  - **Live Bracket Orders**: Parent limit orders are displayed with child stop-loss orders nested beneath them.
  - **Interactive Cancellations**: Click **Cancel ❌** next to any active order to cancel it on the broker's books.
  - **Live Execution Log**: Shows fills, side (bought/sold), shares, price, and commissions.
  - **Emergency Kill Switch**: Press the red button to instantly cancel all orders and flatten positions on Gateway/TWS.

### 3. Run the Automated Live Trader Loop (`run_live_trader.py`)
We have created the production runner [run_live_trader.py](file:///d:/Documents/_MyStuff/Projects/TradingAlgorithmProject/run_live_trader.py) which handles all steps of the daily execution loop.

#### Available CLI Parameters
- `--tickers`: Comma-separated list of symbols to trade (e.g., `--tickers AAPL,MSFT,TSLA`). Default is `AAPL,MSFT`.
- `--port`: API Socket Port. Use **`4002`** for IB Gateway Paper or **`7497`** for TWS Paper. Default is `4002`.
- `--live`: Boolean flag. By default, the script runs in **dry-run** mode for safety. You must include `--live` to send real paper-trading orders.
- `--risk`: Fraction of total portfolio equity to risk per trade. Default is `0.01` (representing 1%).
- `--client-id`: Unique client socket ID to connect to TWS. Default is `1`.

#### Running Steps
1. **Execute in Dry-Run Mode** (Safe verification):
   Before letting the script place orders, run it in simulation mode to verify connections and download market data:
   ```powershell
   python run_live_trader.py --tickers AAPL,MSFT --port 4002
   ```
   - *Expected Output*: You should see `Mode: DRY RUN (MOCK)`. The system will fetch SPY and AAPL/MSFT data, train models, check event blackouts, and log a `HOLD`, `BUY`, or `SELL` signal without sending orders.

2. **Execute in Live Paper-Trading Mode** (Sends real orders):
   To allow the system to connect and place bracket orders on TWS/Gateway:
   ```powershell
   python run_live_trader.py --tickers AAPL,MSFT --port 4002 --live
   ```
   - *Expected Output*: You should see `Mode: LIVE PAPER TRADING`. If a buy signal is generated and passes the Risk Engine (leverage/concentration limits), the bracket order (Entry Limit + Standing Stop-Loss) will be submitted to the broker.

3. **Schedule the Daily Execution**:
   To run this script automatically on your machine, set up a cron job (Linux/macOS) or Windows Task Scheduler.
   - For daily equities, configure the scheduler to run **once a day, 15 minutes before the market close (3:45 PM EST)** or **shortly after market open (9:45 AM EST)**.
   - Example Windows PowerShell Task Action:
     ```powershell
     Program/script: python
     Add arguments: D:\Documents\_MyStuff\Projects\TradingAlgorithmProject\run_live_trader.py --tickers AAPL,MSFT --port 4002 --live
     ```

---

## 🛡️ Step 4: Testing Risk Control Fail-Safes in Paper Mode

It is critical to test your safety valves in a simulated market before deploying real capital.

### Test 1: Verifying Standing Stop-Loss Orders
1. Generate a mock buy signal or force-trigger a small bracket order through your code.
2. Look at the **TWS / Trader Workstation Orders tab**.
3. You should see two orders:
   - A **BUY LIMIT** order (State: *Pre-Submitted* or *Active*).
   - An attached **SELL STOP** order (State: *Child / Standing Order*).
4. Verify that if you manually cancel the parent BUY order, TWS automatically cancels the child STOP order.

### Test 2: Verifying the Emergency Kill Switch (Manual)
1. With open positions active in your paper trading account, go to the **Streamlit Dashboard**.
2. Click the large red **🚨 TRIGGER EMERGENCY KILL SWITCH** button.
3. Observe TWS/Gateway immediately:
   - Any active orders are instantly cancelled.
   - Market orders are submitted to close all positions.
4. Attempt to place a new trade using your script. You should see the script immediately reject the trade with the reason: `Kill switch is active. No orders permitted.`
5. Go to the dashboard and click **Reset Persistent Kill Switch Lock** to re-enable trading after you have investigated.

---

## 🔍 Troubleshooting Connections

### 1. Connection Refused
If the script returns `IBKR connection failed`:
- Verify TWS or Gateway is open and fully logged in.
- Double-check the **Socket Port** in TWS/Gateway settings matches your code port (`7497` vs `4002`).
- Check if another application or script is already using `client_id=1`. If so, change it to a unique integer (e.g., `client_id=2`).

### 2. "No Market Data Permissions" Warnings
IBKR API requires active market data subscriptions to retrieve real-time prices for specific tickers. If you do not have subscriptions:
- The `yfinance` ingestion engine will continue to provide daily historical and delayed price data safely.
- For live executions, you can leverage yfinance's pricing snapshots as a reliable feed fallback in paper trading.
