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

### 2. Run the Streamlit Dashboard
Launch the dashboard to monitor live equity, open positions, recent trade logs, and keep the Manual Emergency Kill Switch accessible:
```powershell
streamlit run dashboard/streamlit_app.py
```
Open the local URL (typically `http://localhost:8501`) in your browser.

### 3. Run Ingestion and Live Execution Loop
Create a main runner script (e.g. `run_live_system.py`) that executes your daily cycle. It should perform the following loop:
1. Check if the **Kill Switch** is active (`risk_controls.is_kill_switch_active()`). If active, halt.
2. Ingest daily prices (`DataIngester`) and save to local storage (`LocalParquetStore`).
3. Compute features (`compute_features()`).
4. Generate Model Predictions (direction probability, volatility forecasting, beta filters).
5. Generate Signal (`SignalGenerator.generate_signals()`).
6. If a `BUY` or `SELL` signal is generated:
   - Query current equity and exposures via the client.
   - Run the trade through `risk_controls.validate_proposed_order()`.
   - Compute size and stop-loss level (`PositionSizer.calculate_position_size()`).
   - Submit the bracket order via `client.place_bracket_order()`.
7. Log the transaction (`AuditLogger.log_event()`).

Run the loop on a schedule (e.g., using `cron` on Linux or Windows Task Scheduler) shortly after market close or before market open.

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
