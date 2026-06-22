import os
import sys
import asyncio
from datetime import datetime, timedelta
import pandas as pd

# Set event loop policy for Windows to avoid set_wakeup_fd errors
if sys.platform == 'win32':
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except AttributeError:
        pass

from data.ingestion.ingest import DataIngester
from data.storage.store import LocalParquetStore
from data.validation.pit_validation import validate_ohlcv_schema, check_pit_integrity
from backtest.walk_forward import WalkForwardBacktester

def main():
    print("=== STARTING END-TO-END ALGORITHMIC TRADING SYSTEM DEMO ===")
    
    # 1. Ingest Data
    ingester = DataIngester()
    store = LocalParquetStore(root_dir="data_store")
    
    start_date = (datetime.now() - timedelta(days=500)).strftime('%Y-%m-%d')
    end_date = datetime.now().strftime('%Y-%m-%d')
    
    ticker = 'AAPL'
    index_ticker = 'SPY'
    
    print(f"Ingesting daily data for {ticker} and {index_ticker} from {start_date} to {end_date}...")
    df_ticker = ingester.fetch_historical_ohlcv(ticker, start_date, end_date)
    df_index = ingester.fetch_historical_ohlcv(index_ticker, start_date, end_date)
    
    if df_ticker.empty or df_index.empty:
        print("Error: Could not retrieve market data. Exiting.")
        return
        
    print(f"Downloaded {len(df_ticker)} bars for {ticker} and {len(df_index)} bars for {index_ticker}.")
    
    # 2. Validate Data
    print("Validating data schemas and Point-in-Time integrity...")
    ticker_ok = validate_ohlcv_schema(df_ticker) and check_pit_integrity(df_ticker)
    index_ok = validate_ohlcv_schema(df_index) and check_pit_integrity(df_index)
    
    if not (ticker_ok and index_ok):
        print("Data validation failed. Exiting.")
        return
        
    print("Data validation passed successfully.")
    
    # 3. Store Data
    print("Saving datasets to local versioned storage...")
    store.save_data(ticker, 'ohlcv', df_ticker)
    store.save_data(index_ticker, 'ohlcv', df_index)
    
    # Reload from storage to ensure store integrity
    loaded_ticker = store.load_data(ticker, 'ohlcv')
    loaded_index = store.load_data(index_ticker, 'ohlcv')
    
    # 4. Run Backtester
    print("Initializing Walk-Forward Backtester (Rolling out-of-sample)...")
    # Setting small train/test windows for quick demo execution
    backtester = WalkForwardBacktester(
        train_window_bars=150,
        test_window_bars=30,
        initial_capital=100000.0,
        risk_fraction=0.01,
        confidence_threshold=0.52
    )
    
    print(f"Running out-of-sample backtest on {ticker} vs {index_ticker}...")
    perf = backtester.run_backtest(ticker, loaded_ticker, loaded_index)
    
    if perf.empty:
        print("Backtest failed or returned no results.")
        return
        
    # 5. Output Results
    initial_val = perf['equity'].iloc[0]
    final_val = perf['equity'].iloc[-1]
    total_ret = (final_val - initial_val) / initial_val
    trades_taken = perf['position_active'].diff().clip(lower=0).sum()
    
    print("\n=== DEMO BACKTEST RESULTS ===")
    print(f"Initial Portfolio Value : ${initial_val:,.2f}")
    print(f"Final Portfolio Value   : ${final_val:,.2f}")
    print(f"Cumulative Return       : {total_ret*100:.2f}%")
    print(f"Approximate Trades Taken: {int(trades_taken)}")
    print("===========================================")

if __name__ == '__main__':
    main()
