import os
import sys

# Resolve project root import paths for direct script execution
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import argparse
import asyncio
import pandas as pd
from datetime import datetime, timedelta

# Adjust asyncio event loop policy on Windows to prevent set_wakeup_fd errors with ib_insync
if sys.platform == 'win32':
    try:
        if not isinstance(asyncio.get_event_loop_policy(), asyncio.WindowsSelectorEventLoopPolicy):
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except AttributeError:
        pass

from ib_insync import IB, LimitOrder, StopOrder, MarketOrder
from data.storage.store import LocalParquetStore
from data.validation.pit_validation import validate_ohlcv_schema, check_pit_integrity
from features.library import compute_features
from models.direction_model.model import DirectionModel
from models.volatility_model.model import VolatilityModel
from models.factor_filter.filter import FactorFilter
from strategy_signals.generator import SignalGenerator
from monitoring.logger import AuditLogger

from multi_asset_system.data_ingester import IBKRDataIngester
from multi_asset_system.risk_controls import MultiAssetRiskControls, MultiAssetSizer

def place_multi_asset_bracket(ib, contract, action, shares, limit_price, stop_loss_price, dry_run=True):
    """Submits a multi-asset bracket order structure to TWS/Gateway."""
    if dry_run:
        print(f"[MOCK MULTI-ASSET ORDER] {action} {shares} contracts/shares of {contract.symbol} @ {limit_price:.4f}. Stop loss: {stop_loss_price:.4f}")
        return [9999, 9998]
        
    try:
        parent_id = ib.client.getReqId()
        
        # Parent Entry Order
        parent = LimitOrder(action, shares, limit_price)
        parent.orderId = parent_id
        parent.transmit = False
        
        # Standing Stop Loss Child Order
        stop_action = 'SELL' if action.upper() == 'BUY' else 'BUY'
        stop = StopOrder(stop_action, shares, stop_loss_price)
        stop.parentId = parent_id
        stop.transmit = True
        
        ib.placeOrder(contract, parent)
        ib.placeOrder(contract, stop)
        
        print(f"Placed live bracket for {contract.symbol}: {action} {shares} @ {limit_price:.4f} with SL @ {stop_loss_price:.4f}")
        return [parent_id, parent_id + 1]
    except Exception as e:
        print(f"Error submitting bracket order: {e}")
        return []

def run_multi_asset_cycle(tickers: list, port: int, client_id: int, live: bool, risk_ctrl, sizer):
    dry_run = not live
    print(f"\n--- STARTING MULTI-ASSET TRADING CYCLE: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---")
    print(f"Mode: {'LIVE PAPER TRADING' if live else 'DRY RUN (MOCK)'} | Port: {port} | Client ID: {client_id}")

    # Safety limits: Cap ticker list at 25 to prevent socket overload
    if len(tickers) > 25:
        print(f"Warning: Ticker list has {len(tickers)} symbols. Capping to the first 25 to prevent system fatigue.")
        tickers = tickers[:25]

    logger = AuditLogger("audit.log")
    store = LocalParquetStore(root_dir="data_store")
    
    # Check Kill Switch
    if risk_ctrl.is_kill_switch_active():
        details = risk_ctrl.get_kill_switch_details()
        print(f"[WARNING] Skipping cycle. PERSISTENT KILL SWITCH IS ACTIVE. Reason: {details.get('reason', 'N/A')}")
        return

    # Initialize shared IB session for ingester and execution
    ib = IB()
    try:
        if not ib.connect("127.0.0.1", port, clientId=client_id):
            print("[ERROR] Failed to connect to TWS/Gateway. Halting cycle.")
            return
            
        ingester = IBKRDataIngester(ib_client=ib)
        
        # 1. Fetch current portfolio NLV and positions
        if dry_run:
            portfolio_value = 100000.0
            active_positions = {}
        else:
            # Query equity
            portfolio_value = 100000.0
            for item in ib.accountSummary():
                if item.tag == 'NetLiquidation':
                    portfolio_value = float(item.value)
                    break
            
            # Query positions
            active_positions = {p.contract.symbol: p.position for p in ib.positions() if p.position != 0}
            
        print(f"Portfolio Value (NLV): ${portfolio_value:,.2f}")
        print(f"Open Positions: {active_positions}")
        
        # 2. Ingest SPY index benchmark for Fama-French regression
        # SPY is default benchmark for stock beta; for simplicity, we use it for index beta filter
        df_index = ingester.fetch_historical_ohlcv('SPY', duration_days=365)
        if df_index.empty:
            print("[ERROR] SPY index benchmark data unavailable. Halting loop.")
            return
        store.save_data('SPY', 'ohlcv', df_index)
        loaded_index = store.load_data('SPY', 'ohlcv')
        
        blackout_df = ingester.fetch_macro_calendar()

        # 3. Evaluate each ticker in universe
        for ticker in tickers:
            # Respect TWS pacing delay limits
            print(f"\nSleeping 1.0 second to respect TWS API pacing limits...")
            time.sleep(1.0)
            
            print(f"Evaluating ticker: {ticker}...")
            
            # Ingest data directly from IBKR socket
            df_raw = ingester.fetch_historical_ohlcv(ticker, duration_days=365)
            if df_raw.empty:
                print(f"[WARNING] No historical data returned for {ticker}. Skipping.")
                continue
                
            if not validate_ohlcv_schema(df_raw) or not check_pit_integrity(df_raw):
                print(f"[WARNING] Data validation failed for {ticker}. Skipping.")
                continue
                
            store.save_data(ticker, 'ohlcv', df_raw)
            loaded_ticker = store.load_data(ticker, 'ohlcv')
            
            # 4. Compute shared features
            df_feats = compute_features(loaded_ticker, loaded_index)
            
            # 5. Fit models
            # Direction return model
            dir_model = DirectionModel(forward_window=5)
            dir_model.fit(df_feats)
            probs = dir_model.predict_probability(df_feats)
            latest_prob = probs.iloc[-1]
            
            # Volatility forecasting
            vol_model = VolatilityModel(fallback_window=20)
            vol_model.fit(df_feats['ret_1d'])
            atr_val = df_feats['atr_14'].iloc[-1]
            
            # Factor Filter
            factor_filter = FactorFilter(p_value_threshold=0.05)
            filter_results = factor_filter.analyze_exposure(df_feats['ret_1d'].tail(60), df_feats['index_ret_1d'].tail(60))
            
            # 6. Generate signals
            signal_gen = SignalGenerator(confidence_threshold=0.55, blackout_window_days=3)
            signal = signal_gen.generate_signals(
                ticker=ticker,
                df=df_feats,
                direction_probs=probs,
                factor_filter_results=filter_results,
                current_time=datetime.now(),
                blackout_df=blackout_df
            )
            
            print(f"Signal Result: {signal['action']} (Confidence: {latest_prob:.2f}) | Reason: {signal.get('reason', 'N/A')}")
            
            # 7. Execute order if signal generated
            action = signal['action']
            if action in ['BUY', 'SELL']:
                contract = ingester.parse_contract(ticker)
                
                # Check exposure limits and validate proposed trade
                sizing_res = sizer.calculate_size(ticker, portfolio_value, signal['price'], atr_val, action)
                shares = sizing_res['shares']
                stop_loss = sizing_res['stop_loss_price']
                pos_val = sizing_res.get('position_value', shares * signal['price'])
                
                if shares <= 0:
                    print(f"[WARNING] Position sizing returned 0 contracts/shares. Reason: {sizing_res.get('reason', 'N/A')}")
                    continue
                    
                # Calculate current total exposure
                # In dry run, we use mock approximation
                current_exposure = 0.0
                if not dry_run:
                    current_exposure = sum([abs(p.position * p.marketPrice) for p in ib.positions() if p.position != 0])
                
                allowed, risk_reason = risk_ctrl.validate_new_order(
                    symbol=ticker,
                    current_portfolio_value=portfolio_value,
                    current_exposure=current_exposure,
                    proposed_order_value=pos_val,
                    active_positions=active_positions
                )
                
                if not allowed:
                    print(f"[ERROR] Order REJECTED by Risk controls: {risk_reason}")
                    logger.log_event("ORDER_REJECTED", {
                        "ticker": ticker,
                        "action": action,
                        "shares": shares,
                        "reason": risk_reason
                    })
                    continue
                
                # Submit bracket order
                print(f"Placing bracket: {action} {shares} contracts/shares of {ticker} with standing stop-loss at {stop_loss}")
                order_ids = place_multi_asset_bracket(ib, contract, action, shares, signal['price'], stop_loss, dry_run=dry_run)
                
                logger.log_event("ORDER_PLACED", {
                    "ticker": ticker,
                    "action": action,
                    "shares": shares,
                    "limit_price": signal['price'],
                    "stop_loss": stop_loss,
                    "order_ids": order_ids,
                    "portfolio_value": portfolio_value,
                    "asset_class": risk_ctrl.get_asset_class(ticker)
                })
                
                # Mock update positions for logging sequential limit checks in dry-run
                if dry_run:
                    active_positions[ticker] = shares if action == 'BUY' else -shares

        # 8. Check Drawdown Breaker
        eq_file = "equity_history.csv"
        if not os.path.exists(eq_file):
            pd.DataFrame([{'timestamp': datetime.now().isoformat(), 'equity': portfolio_value}]).to_csv(eq_file, index=False)
        else:
            eq_df = pd.read_csv(eq_file)
            new_row = pd.DataFrame([{'timestamp': datetime.now().isoformat(), 'equity': portfolio_value}])
            eq_df = pd.concat([eq_df, new_row], ignore_index=True)
            eq_df.to_csv(eq_file, index=False)
            risk_ctrl.check_drawdown_breaker(eq_df['equity'])

    finally:
        if ib.isConnected():
            ib.disconnect()
        print("\n--- MULTI-ASSET CYCLE COMPLETE ---")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Multi-Asset Live Trading Runner for IBKR.")
    parser.add_argument('--tickers', type=str, default="AAPL,EURUSD,ES-202609-GLOBEX", 
                        help="Comma-separated list of symbols (e.g. AAPL,EURUSD,ES-202609-GLOBEX).")
    parser.add_argument('--port', type=int, default=4002, help="API Socket Port (Use 4002 for Gateway Paper, 7497 for TWS Paper).")
    parser.add_argument('--client-id', type=int, default=11, help="Unique socket client ID.")
    parser.add_argument('--live', action='store_true', help="Disable dry-run mode and send real orders.")
    
    args = parser.parse_args()
    symbols = [s.strip() for s in args.tickers.split(',')]
    
    risk_controls = MultiAssetRiskControls(lock_file_path="kill_switch.lock")
    sizer = MultiAssetSizer(stop_atr_mult=2.0)
    
    run_multi_asset_cycle(
        tickers=symbols,
        port=args.port,
        client_id=args.client_id,
        live=args.live,
        risk_ctrl=risk_controls,
        sizer=sizer
    )
