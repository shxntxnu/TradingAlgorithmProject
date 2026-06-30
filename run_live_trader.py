import os
import sys
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

from data.ingestion.ingest import DataIngester
from data.storage.store import LocalParquetStore
from data.validation.pit_validation import validate_ohlcv_schema, check_pit_integrity
from features.library import compute_features
from models.direction_model.model import DirectionModel
from models.volatility_model.model import VolatilityModel
from models.factor_filter.filter import FactorFilter
from strategy_signals.generator import SignalGenerator
from risk.sizing import PositionSizer
from risk.controls import RiskControls
from execution.ibkr_client import IBKRClient
from monitoring.logger import AuditLogger

def run_trading_cycle(tickers: list, port: int, client_id: int, live: bool, risk_frac: float):
    dry_run = not live
    print(f"\n--- STARTING TRADING CYCLE: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---")
    print(f"Mode: {'LIVE PAPER TRADING' if live else 'DRY RUN (MOCK)'} | Port: {port} | Client ID: {client_id}")

    # 1. Initialize core system utilities
    risk_controls = RiskControls(lock_file_path="kill_switch.lock")
    logger = AuditLogger("audit.log")
    ingester = DataIngester()
    store = LocalParquetStore(root_dir="data_store")
    
    # 2. Safety Check: Persistent Kill Switch Check
    if risk_controls.is_kill_switch_active():
        details = risk_controls.get_kill_switch_details()
        msg = f"Skipping trading cycle. PERSISTENT KILL SWITCH IS ACTIVE. Reason: {details.get('reason', 'N/A')}"
        print(f"⚠️ {msg}")
        logger.log_event("CYCLE_SKIPPED", {"reason": "Kill switch is active", "details": details})
        return

    # 3. Connect to Broker Gateway / TWS
    client = IBKRClient(port=port, client_id=client_id, dry_run=dry_run)
    if not client.connect():
        print("❌ Failed to establish connection to IBKR Gateway/TWS. Exiting cycle.")
        logger.log_event("CYCLE_ERROR", {"error": "Broker connection failed"})
        return

    try:
        # 4. Fetch Account Valuation
        portfolio_value = client.get_equity()
        positions = client.get_positions()
        print(f"Current Portfolio Value (NLV): ${portfolio_value:,.2f}")
        print(f"Current Open Positions: {positions}")

        # Ingest benchmark index data (SPY) for Fama-French regression
        start_date = (datetime.now() - timedelta(days=500)).strftime('%Y-%m-%d')
        end_date = datetime.now().strftime('%Y-%m-%d')
        
        print("Ingesting market index benchmark (SPY)...")
        df_index = ingester.fetch_historical_ohlcv('SPY', start_date, end_date)
        if df_index.empty or not validate_ohlcv_schema(df_index) or not check_pit_integrity(df_index):
            print("❌ Benchmark data invalid or unavailable. Halting cycle for safety.")
            logger.log_event("CYCLE_ERROR", {"error": "Invalid benchmark index data"})
            return
            
        store.save_data('SPY', 'ohlcv', df_index)
        loaded_index = store.load_data('SPY', 'ohlcv')
        
        # Load macro blackouts
        blackout_calendar = ingester.fetch_macro_calendar()

        # 5. Process each target ticker in the trading universe
        for ticker in tickers:
            print(f"\nEvaluating ticker: {ticker}...")
            
            # Fetch and store price data
            df_raw = ingester.fetch_historical_ohlcv(ticker, start_date, end_date)
            if df_raw.empty:
                print(f"⚠️ No data received for {ticker}. Skipping.")
                continue
                
            if not validate_ohlcv_schema(df_raw) or not check_pit_integrity(df_raw):
                print(f"⚠️ Data validation checks failed for {ticker}. Skipping.")
                continue
                
            store.save_data(ticker, 'ohlcv', df_raw)
            loaded_ticker = store.load_data(ticker, 'ohlcv')
            
            # 6. Compute Features
            df_feats = compute_features(loaded_ticker, loaded_index)
            
            # 7. Model Ensemble Predictions
            # A - Directional return model
            dir_model = DirectionModel(forward_window=5)
            # Train model on rolling history
            dir_model.fit(df_feats)
            probs = dir_model.predict_probability(df_feats)
            latest_prob = probs.iloc[-1]
            
            # B - Volatility forecasting
            vol_model = VolatilityModel(fallback_window=20)
            vol_model.fit(df_feats['ret_1d'])
            atr_val = df_feats['atr_14'].iloc[-1]
            
            # C - Fama-French/Beta regression filter
            factor_filter = FactorFilter(p_value_threshold=0.05)
            filter_results = factor_filter.analyze_exposure(df_feats['ret_1d'].tail(60), df_feats['index_ret_1d'].tail(60))
            
            # 8. Generate Trading Signals
            signal_gen = SignalGenerator(confidence_threshold=0.55)
            signal = signal_gen.generate_signals(
                ticker=ticker,
                df=df_feats,
                direction_probs=probs,
                factor_filter_results=filter_results,
                current_time=datetime.now(),
                blackout_df=blackout_calendar
            )
            
            print(f"Signal Result: {signal['action']} (Confidence: {latest_prob:.2f}) | Reason: {signal.get('reason', 'N/A')}")
            
            # 9. Handle Order Execution
            action = signal['action']
            if action in ['BUY', 'SELL']:
                current_shares = positions.get(ticker, 0)
                
                # Double check if we already hold a position in the signal direction to prevent overexposure
                if (action == 'BUY' and current_shares > 0) or (action == 'SELL' and current_shares < 0):
                    print(f"Already hold {current_shares} shares of {ticker} in signal direction. Skipping entry.")
                    continue
                
                # Sizing calculations
                sizer = PositionSizer(risk_fraction=risk_frac, stop_atr_mult=2.0)
                entry_price = signal['price']
                sizing_res = sizer.calculate_position_size(portfolio_value, entry_price, atr_val, action)
                shares = sizing_res['shares']
                stop_loss = sizing_res['stop_loss_price']
                position_val = sizing_res.get('position_value', shares * entry_price)
                
                if shares <= 0:
                    print(f"⚠️ Position sizing returned 0 shares. Reason: {sizing_res.get('reason', 'N/A')}")
                    continue
                    
                # 10. Portfolio Risk Checks (Leverage, Concentration)
                current_exposure = sum([abs(pos * entry_price) for pos in positions.values()]) # rough approximation
                current_ticker_exp = abs(current_shares * entry_price)
                
                allowed, risk_reason = risk_controls.validate_proposed_order(
                    current_portfolio_value=portfolio_value,
                    current_exposure=current_exposure,
                    proposed_order_value=position_val,
                    current_ticker_exposure=current_ticker_exp
                )
                
                if not allowed:
                    print(f"❌ Order REJECTED by Risk Engine: {risk_reason}")
                    logger.log_event("ORDER_REJECTED", {
                        "ticker": ticker,
                        "action": action,
                        "shares": shares,
                        "reason": risk_reason
                    })
                    continue
                
                # 11. Place Standing Broker Bracket Order
                print(f"Placing standing bracket order for {ticker}: {action} {shares} shares @ {entry_price:.2f} with stop-loss at {stop_loss:.2f}")
                order_ids = client.place_bracket_order(
                    ticker=ticker,
                    action=action,
                    shares=shares,
                    limit_price=entry_price,
                    stop_loss_price=stop_loss
                )
                
                logger.log_event("ORDER_PLACED", {
                    "ticker": ticker,
                    "action": action,
                    "shares": shares,
                    "limit_price": entry_price,
                    "stop_loss": stop_loss,
                    "order_ids": order_ids,
                    "portfolio_value": portfolio_value
                })

        # 12. Check Portfolio Drawdown Breaker
        # For drawdown breaker to work dynamically, we append the latest equity to a local log
        # and evaluate our peak-to-trough curve.
        equity_log_file = "equity_history.csv"
        if not os.path.exists(equity_log_file):
            pd.DataFrame([{'timestamp': datetime.now().isoformat(), 'equity': portfolio_value}]).to_csv(equity_log_file, index=False)
        else:
            eq_df = pd.read_csv(equity_log_file)
            new_row = pd.DataFrame([{'timestamp': datetime.now().isoformat(), 'equity': portfolio_value}])
            eq_df = pd.concat([eq_df, new_row], ignore_index=True)
            eq_df.to_csv(equity_log_file, index=False)
            
            # Check drawdown circuit breaker
            risk_controls.check_drawdown_breaker(eq_df['equity'])

    finally:
        # Disconnect cleanly from the TWS session
        client.disconnect()
        print("\n--- CYCLE COMPLETE ---")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Live Trading Execution Loop for IBKR Gateway / TWS.")
    parser.add_argument('--tickers', type=str, default="AAPL,MSFT", help="Comma-separated list of symbols to trade.")
    parser.add_argument('--port', type=int, default=4002, help="API Socket Port (Use 4002 for Gateway Paper, 7497 for TWS Paper).")
    parser.add_argument('--client-id', type=int, default=1, help="Unique socket client ID.")
    parser.add_argument('--live', action='store_true', help="Disable Dry Run and send real orders to the broker.")
    parser.add_argument('--risk', type=float, default=0.01, help="Capital percentage to risk per trade (e.g. 0.01 for 1%).")
    
    args = parser.parse_args()
    symbols = [s.strip().upper() for s in args.tickers.split(',')]
    
    run_trading_cycle(
        tickers=symbols,
        port=args.port,
        client_id=args.client_id,
        live=args.live,
        risk_frac=args.risk
    )
