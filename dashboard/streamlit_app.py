import os
import sys
import time
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime

import asyncio

# Adjust Windows event loop policy to avoid set_wakeup_fd issues
if sys.platform == 'win32':
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except AttributeError:
        pass

# Ensure that an event loop exists for this background thread (Streamlit's ScriptRunner thread)
try:
    asyncio.get_event_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

# Import modules from our project
from risk.controls import RiskControls
from execution.ibkr_client import IBKRClient
from monitoring.logger import AuditLogger

# Page configuration
st.set_page_config(page_title="EquityLens - Live Order & Execution Monitor", layout="wide")

# Custom premium styling (Slate and Blue palette, glassmorphism highlights)
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap');
    html, body, [class*="css"] {
        font-family: 'Outfit', sans-serif;
    }
    .main-header { font-size: 38px; font-weight: 700; color: #1E3A8A; margin-bottom: 5px; }
    .subheader { font-size: 16px; color: #64748B; margin-bottom: 25px; }
    .status-card { padding: 18px; border-radius: 12px; margin-bottom: 20px; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.05); }
    .kill-active { background-color: #FEF2F2; border: 1.5px solid #F87171; color: #991B1B; }
    .system-normal { background-color: #ECFDF5; border: 1.5px solid #34D399; color: #065F46; }
    .section-box { background-color: #F8FAFC; border: 1px solid #E2E8F0; padding: 20px; border-radius: 12px; margin-bottom: 20px; }
    .order-parent { background-color: #F1F5F9; font-weight: 600; }
    .order-child { padding-left: 20px; color: #475569; font-style: italic; }
    </style>
""", unsafe_allow_html=True)

# 1. SIDEBAR - Session Configuration & Cache Resource
st.sidebar.title("🔌 Connection settings")

run_mode = st.sidebar.selectbox(
    "Execution Mode", 
    ["Dry-Run (Mock / Simulation)", "Live Paper Trading (TWS / Gateway)"],
    index=0
)
live_mode = (run_mode == "Live Paper Trading (TWS / Gateway)")

host = st.sidebar.text_input("IBKR Host Address", "127.0.0.1")
port = st.sidebar.number_input("API Socket Port", value=4002, help="Use 4002 for Gateway Paper, 7497 for TWS Paper")
client_id = st.sidebar.number_input("Socket Client ID", value=99, help="Must be unique (default 99 avoids collision with trading loop)")
auto_refresh = st.sidebar.checkbox("Auto-refresh (every 5 seconds)", value=True)

# Latch Cache client
@st.cache_resource
def get_cached_ib_client(host_addr, port_num, cid, is_live):
    # If not is_live, we enforce dry_run=True inside IBKRClient
    cli = IBKRClient(host=host_addr, port=port_num, client_id=cid, dry_run=not is_live)
    cli.connect()
    return cli

client = get_cached_ib_client(host, port, client_id, live_mode)
risk_ctrl = RiskControls(lock_file_path="kill_switch.lock")
logger = AuditLogger("audit.log")

# Connection Banner status
st.markdown('<div class="main-header">EquityLens Live Execution Panel</div>', unsafe_allow_html=True)
if client.dry_run:
    st.markdown('<div class="subheader">Running in Simulated Dry-Run Mode. Connect to TWS or IB Gateway to see live orders.</div>', unsafe_allow_html=True)
else:
    st.markdown(f'<div class="subheader">Connected to Interactive Brokers Gateway at {host}:{port} (Active Client ID {client_id})</div>', unsafe_allow_html=True)

# 2. Check and Display Kill Switch Panel
is_killed = risk_ctrl.is_kill_switch_active()
details = risk_ctrl.get_kill_switch_details()

if is_killed:
    st.markdown(f"""
        <div class="status-card kill-active">
            <h4>🚨 SYSTEM HALTED BY PERSISTENT KILL SWITCH</h4>
            <p style="margin: 4px 0;"><strong>Reason:</strong> {details.get('reason', 'N/A')} (Activated at: {details.get('timestamp', 'N/A')})</p>
            <p style="margin: 0; font-size: 13px;">New orders are rejected. Click "Reset Latch" below to clear.</p>
        </div>
    """, unsafe_allow_html=True)
else:
    st.markdown("""
        <div class="status-card system-normal">
            <h4>🟢 RISK ENGINE ACTIVE & OPERATIONAL</h4>
            <p style="margin: 0; font-size: 13px;">Portfolio drawdowns and leverage parameters within safe operating thresholds.</p>
        </div>
    """, unsafe_allow_html=True)

# 3. Main Dashboard Layout (Grid)
col_controls, col_charts = st.columns([1, 2])

with col_controls:
    st.subheader("System Control Actions")
    if st.button("🚨 TRIGGER EMERGENCY KILL SWITCH", type="primary", use_container_width=True):
        client.flatten_positions_and_kill(risk_ctrl)
        logger.log_event("KILL_SWITCH_TRIGGERED", {"triggered_by": "Streamlit Dashboard", "reason": "Manual dashboard trigger"})
        st.success("Kill switch activated! Orders cancelled and positions flattened.")
        st.rerun()
        
    if is_killed:
        if st.button("🔓 Reset Persistent Kill Switch Lock", use_container_width=True):
            risk_ctrl.reset_kill_switch()
            logger.log_event("KILL_SWITCH_RESET", {"triggered_by": "Streamlit Dashboard"})
            st.success("System operational again!")
            st.rerun()
            
    st.markdown("---")
    st.write(f"**Net Liquidation Value:** ${client.get_equity():,.2f}")
    st.write(f"**Active Mode:** `{'SIMULATOR' if client.dry_run else 'LIVE PAPER'}`")

with col_charts:
    # Render interactive equity performance curve
    st.subheader("Account Net Liquidation Value (NLV) Curve")
    # Read history log if exists, else render sample
    eq_file = "equity_history.csv"
    if os.path.exists(eq_file):
        eq_data = pd.read_csv(eq_file)
        eq_data['timestamp'] = pd.to_datetime(eq_data['timestamp'])
    else:
        # Mock curve
        dates = pd.date_range(end=datetime.now(), periods=50)
        equities = 100000.0 * np.cumprod(1 + np.random.normal(0.0002, 0.005, 50))
        eq_data = pd.DataFrame({'timestamp': dates, 'equity': equities})

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=eq_data['timestamp'], y=eq_data['equity'], mode='lines+markers', name='NLV', line=dict(color='#2563EB', width=2)))
    fig.update_layout(
        margin=dict(l=10, r=10, t=10, b=10),
        height=200,
        xaxis_title="Date/Time",
        yaxis_title="Account Equity (USD)"
    )
    st.plotly_chart(fig, use_container_width=True)

# 4. LIVE ORDERS & LINKAGES (BRACKETS) MONITOR
st.markdown("---")
st.subheader("📈 Live Orders Monitor")

if client.dry_run:
    st.info("Showing mock open orders (Switch mode to 'Live Paper' in the sidebar to load from Gateway).")
    # Simulated orders list
    mock_orders_df = pd.DataFrame([
        {'Order ID': 1024, 'Parent ID': 'None (Parent)', 'Ticker': 'AAPL', 'Action': 'BUY', 'Quantity': 150, 'Type': 'LMT', 'Price': 185.20, 'Status': 'Submitted'},
        {'Order ID': 1025, 'Parent ID': 1024, 'Ticker': 'AAPL', 'Action': 'SELL', 'Quantity': 150, 'Type': 'STP', 'Price': 180.20, 'Status': 'PreSubmitted (Standing SL)'},
        {'Order ID': 1026, 'Parent ID': 'None (Parent)', 'Ticker': 'MSFT', 'Action': 'BUY', 'Quantity': 80, 'Type': 'LMT', 'Price': 420.50, 'Status': 'Submitted'},
        {'Order ID': 1027, 'Parent ID': 1026, 'Ticker': 'MSFT', 'Action': 'SELL', 'Quantity': 80, 'Type': 'STP', 'Price': 410.50, 'Status': 'PreSubmitted (Standing SL)'}
    ])
    st.table(mock_orders_df)
else:
    # Load actual live open orders
    try:
        trades = client.ib.openTrades()
        if not trades:
            st.success("No active pending orders found on the broker.")
        else:
            orders_list = []
            for t in trades:
                orders_list.append({
                    'Order ID': t.order.orderId,
                    'Parent ID': t.order.parentId if t.order.parentId != 0 else 'None (Parent)',
                    'Ticker': t.contract.symbol,
                    'Action': t.order.action,
                    'Quantity': t.order.totalQuantity,
                    'Type': t.order.orderType,
                    'Price': t.order.lmtPrice if t.order.orderType == 'LMT' else t.order.auxPrice,
                    'Status': t.orderStatus.status,
                    '_trade': t # Keep trade object reference for cancellation
                })
            
            df_orders = pd.DataFrame(orders_list)
            
            # Display orders in columns with interactable cancel buttons
            cols = st.columns([1, 1, 1, 1, 1, 1, 1.2, 1.5, 1])
            cols[0].write("**Order ID**")
            cols[1].write("**Parent ID**")
            cols[2].write("**Ticker**")
            cols[3].write("**Action**")
            cols[4].write("**Qty**")
            cols[5].write("**Type**")
            cols[6].write("**Trigger Price**")
            cols[7].write("**Status**")
            cols[8].write("**Action**")
            
            st.markdown("<hr style='margin: 4px 0;'>", unsafe_allow_html=True)
            
            for idx, row in df_orders.iterrows():
                # Nest child stop-loss orders visually
                is_child = row['Parent ID'] != 'None (Parent)'
                style_prefix = "👉 " if is_child else ""
                
                cols = st.columns([1, 1, 1, 1, 1, 1, 1.2, 1.5, 1])
                cols[0].write(f"{style_prefix}{row['Order ID']}")
                cols[1].write(str(row['Parent ID']))
                cols[2].write(row['Ticker'])
                cols[3].write(row['Action'])
                cols[4].write(str(row['Quantity']))
                cols[5].write(row['Type'])
                cols[6].write(f"${row['Price']:.2f}")
                cols[7].write(f"`{row['Status']}`")
                
                # Single Order Cancellation Button
                if cols[8].button("Cancel ❌", key=f"cancel_{row['Order ID']}", use_container_width=True):
                    client.ib.cancelOrder(row['_trade'].order)
                    st.success(f"Sent cancellation request for order {row['Order ID']}.")
                    time.sleep(0.5)
                    st.rerun()
    except Exception as e:
        st.error(f"Error loading live open orders: {e}")

# 5. POSITIONS & HISTORICAL LOGS
st.markdown("---")
col_pos, col_fills = st.columns([1, 1])

with col_pos:
    st.subheader("💼 Active Positions")
    if client.dry_run:
        # Mock positions table
        st.table(pd.DataFrame({
            'Ticker': ['AAPL', 'MSFT'],
            'Shares': [150, 80],
            'Avg Cost': [175.50, 420.25],
            'Market Price': [178.20, 422.10],
            'PnL (Unrealized)': [405.00, 148.00]
        }))
    else:
        try:
            positions = client.ib.positions()
            if not positions:
                st.write("No active open positions on account.")
            else:
                pos_list = []
                for p in positions:
                    pos_list.append({
                        'Ticker': p.contract.symbol,
                        'Shares': p.position,
                        'Avg Cost': f"${p.averageCost:,.2f}",
                        'Market Price': f"${p.marketPrice:,.2f}",
                        'Market Value': f"${p.marketValue:,.2f}"
                    })
                st.table(pd.DataFrame(pos_list))
        except Exception as e:
            st.error(f"Error loading live positions: {e}")

with col_fills:
    st.subheader("📜 Historical Executions (Fills)")
    if client.dry_run:
        st.table(pd.DataFrame({
            'Time': ['15:42:01', '15:42:01'],
            'Ticker': ['SPY', 'AAPL'],
            'Side': ['BOT', 'BOT'],
            'Shares': [100, 150],
            'Price': [500.20, 185.20],
            'Commission': [1.00, 1.00]
        }))
    else:
        try:
            fills = client.ib.fills()
            if not fills:
                st.write("No execution fills recorded in the current session.")
            else:
                fill_list = []
                for f in reversed(fills[-10:]): # Last 10 executions
                    comm = f.commissionReport.commission if f.commissionReport else 0.0
                    fill_list.append({
                        'Time': f.execution.time.strftime('%H:%M:%S') if isinstance(f.execution.time, datetime) else str(f.execution.time),
                        'Ticker': f.contract.symbol,
                        'Side': f.execution.side,
                        'Shares': f.execution.shares,
                        'Price': f"${f.execution.price:,.2f}",
                        'Commission': f"${comm:,.2f}"
                    })
                st.table(pd.DataFrame(fill_list))
        except Exception as e:
            st.error(f"Error loading live execution fills: {e}")

# 6. Live Auto-refresh trigger (renders at bottom)
if auto_refresh:
    time.sleep(5)
    st.rerun()
