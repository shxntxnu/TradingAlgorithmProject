import os
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime

# Import modules from our project
from risk.controls import RiskControls
from execution.ibkr_client import IBKRClient
from monitoring.logger import AuditLogger

# Initialize systems
risk_ctrl = RiskControls(lock_file_path="kill_switch.lock")
client = IBKRClient(dry_run=True) # Defaults to mock for dashboard demo
logger = AuditLogger("audit.log")

st.set_page_config(page_title="EquityLens - Algorithmic Trading Control Panel", layout="wide")

# Styling header
st.markdown("""
    <style>
    .main-header { font-size: 36px; font-weight: bold; color: #1E3A8A; margin-bottom: 20px; }
    .status-panel { padding: 15px; border-radius: 8px; margin-bottom: 20px; }
    .kill-active { background-color: #FEE2E2; border: 2px solid #EF4444; color: #991B1B; }
    .system-normal { background-color: #ECFDF5; border: 2px solid #10B981; color: #065F46; }
    </style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-header">EquityLens Trading Control Panel</div>', unsafe_allow_html=True)

# 1. Check Kill Switch State
is_killed = risk_ctrl.is_kill_switch_active()
details = risk_ctrl.get_kill_switch_details()

if is_killed:
    st.markdown(f"""
        <div class="status-panel kill-active">
            <h3>⚠️ SYSTEM HALTED BY PERSISTENT KILL SWITCH</h3>
            <p><strong>Activated At:</strong> {details.get('timestamp', 'N/A')}</p>
            <p><strong>Reason:</strong> {details.get('reason', 'N/A')}</p>
            <p>All positions have been flattened, pending orders cancelled, and new entries are blocked.</p>
        </div>
    """, unsafe_allow_html=True)
else:
    st.markdown("""
        <div class="status-panel system-normal">
            <h3>🟢 SYSTEM OPERATIONAL</h3>
            <p>Risk parameters within normal ranges. Signal generation and order placement active.</p>
        </div>
    """, unsafe_allow_html=True)

# Layout columns for actions and key metrics
col1, col2 = st.columns([2, 3])

with col1:
    st.subheader("System Controls")
    
    # Large Emergency Kill Switch Button
    if st.button("🚨 TRIGGER EMERGENCY KILL SWITCH", type="primary", use_container_width=True):
        # Flatten and trigger
        client.flatten_positions_and_kill(risk_ctrl)
        logger.log_event("KILL_SWITCH_TRIGGERED", {"triggered_by": "Streamlit Dashboard", "reason": "Manual emergency activation"})
        st.rerun()
        
    if is_killed:
        st.write("To resume trading, verify risk conditions and reset the latch below:")
        if st.button("Reset Persistent Kill Switch Lock", use_container_width=True):
            risk_ctrl.reset_kill_switch()
            logger.log_event("KILL_SWITCH_RESET", {"triggered_by": "Streamlit Dashboard"})
            st.success("Kill switch reset. System set to Operational.")
            st.rerun()

    st.markdown("---")
    st.subheader("Active Risk Parameters")
    st.write(f"**Max Leverage Cap:** {risk_ctrl.max_leverage}x")
    st.write(f"**Max Drawdown Breaker:** {risk_ctrl.max_drawdown_limit * 100:.1f}%")
    st.write(f"**Max Single-Name Concentration:** {risk_ctrl.max_single_name_pct * 100:.1f}%")

with col2:
    st.subheader("Equity Curve & Performance")
    
    # Generate mock equity curve for visualization
    np.random.seed(42)
    days = 100
    base_equity = 100000.0
    daily_returns = np.random.normal(0.0005, 0.006, days)
    # Add a drawdown event in the middle
    daily_returns[40:50] -= 0.015
    
    equity_curve = base_equity * np.cumprod(1 + daily_returns)
    dates = pd.date_range(end=datetime.now(), periods=days)
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=dates, y=equity_curve, mode='lines', name='Account Equity', line=dict(color='#1E3A8A', width=2)))
    fig.update_layout(
        title="Account Net Liquidation Value (NLV)",
        xaxis_title="Date",
        yaxis_title="Equity (USD)",
        margin=dict(l=20, r=20, t=40, b=20),
        height=300
    )
    st.plotly_chart(fig, use_container_width=True)

# Bottom section: Positions & Logs
st.markdown("---")
col_pos, col_log = st.columns([1, 1])

with col_pos:
    st.subheader("Active Positions")
    if is_killed:
        st.info("No open positions (all positions were flattened).")
    else:
        # Render a mock position table
        positions_data = {
            'Ticker': ['AAPL', 'MSFT'],
            'Direction': ['LONG', 'LONG'],
            'Shares': [150, 80],
            'Entry Price': [175.50, 420.25],
            'Current Price': [178.20, 422.10],
            'Stop-Loss (Standing)': [168.00, 405.00],
            'PnL (Unrealized)': ['$405.00', '$148.00']
        }
        st.table(pd.DataFrame(positions_data))

with col_log:
    st.subheader("Audit Event Logs")
    # Read events from logger
    events = logger.read_events()
    if events:
        log_df = pd.DataFrame([
            {
                'Timestamp': e['timestamp'][:19].replace('T', ' '),
                'Event Type': e['event_type'],
                'Details': str(e['details'])
            } for e in reversed(events[-10:]) # last 10 events
        ])
        st.dataframe(log_df, use_container_width=True)
    else:
        st.write("No audit events logged yet.")
