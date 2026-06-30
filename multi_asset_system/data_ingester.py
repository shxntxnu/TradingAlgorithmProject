import os
import sys
import asyncio
import pandas as pd
from datetime import datetime, timedelta
from ib_insync import IB, Stock, Forex, Future, Index, Contract

# Adjust Windows event loop policy to avoid set_wakeup_fd issues
if sys.platform == 'win32':
    try:
        if not isinstance(asyncio.get_event_loop_policy(), asyncio.WindowsSelectorEventLoopPolicy):
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except AttributeError:
        pass

class IBKRDataIngester:
    """Retrieves daily historical market data directly from Interactive Brokers Gateway/TWS."""
    
    def __init__(self, ib_client=None):
        self.ib = ib_client or IB()

    def connect(self, host: str = "127.0.0.1", port: int = 4002, client_id: int = 10) -> bool:
        """Connect to TWS or IB Gateway socket."""
        if not self.ib.isConnected():
            try:
                self.ib.connect(host, port, clientId=client_id)
                print(f"Ingester connected to IBKR at {host}:{port}")
                return True
            except Exception as e:
                print(f"Ingester failed to connect: {e}")
                return False
        return True

    def disconnect(self):
        """Disconnect cleanly."""
        if self.ib.isConnected():
            self.ib.disconnect()
            print("Ingester disconnected from IBKR.")

    def parse_contract(self, symbol: str) -> Contract:
        """Parse symbol strings into standard qualified ib_insync Contract objects.
        Supported formats:
        - Forex: 'EURUSD' or 'GBP-USD'
        - Futures: 'ES-202609-GLOBEX' (Symbol-Expiry-Exchange)
        - Stocks/ETFs: 'AAPL', 'SPY' (standard ticker symbol)
        """
        symbol = symbol.upper().strip()
        
        # 1. Parse Futures (e.g., 'ES-202609-GLOBEX')
        if '-' in symbol:
            parts = symbol.split('-')
            if len(parts) == 3:
                # Format: Symbol-YYYYMM-Exchange
                return Future(parts[0], parts[1], parts[2])
            elif len(parts) == 2:
                # Format: Currency1-Currency2 (Forex)
                return Forex(f"{parts[0]}{parts[1]}")
                
        # 2. Parse standard Forex (e.g., 'EURUSD')
        forex_pairs = {'EURUSD', 'GBPUSD', 'AUDUSD', 'USDJPY', 'USDCAD', 'CHFUSD'}
        if len(symbol) == 6 and symbol in forex_pairs:
            return Forex(symbol)
            
        # 3. Default to Stock
        return Stock(symbol, 'SMART', 'USD')

    def fetch_historical_ohlcv(self, symbol: str, duration_days: int = 365) -> pd.DataFrame:
        """Request daily historical bars from TWS/Gateway and format as a standard DataFrame."""
        if not self.ib.isConnected():
            print("Error: Ingester client is not connected to TWS/Gateway.")
            return pd.DataFrame()
            
        contract = self.parse_contract(symbol)
        
        try:
            # Qualify the contract details with IBKR registry
            self.ib.qualifyContracts(contract)
            
            # Determine data representation
            what_to_show = 'TRADES'
            if isinstance(contract, Forex):
                what_to_show = 'MIDPOINT'
            
            print(f"Requesting historical data for {contract.localSymbol or contract.symbol} (WhatToShow: {what_to_show})...")
            bars = self.ib.reqHistoricalData(
                contract,
                endDateTime='',
                durationStr=f'{duration_days} D',
                barSizeSetting='1 day',
                whatToShow=what_to_show,
                useRTH=True,
                formatDate=1
            )
            
            if not bars:
                print(f"Warning: Received empty data from IBKR for {symbol}")
                return pd.DataFrame()
                
            # Convert to standard format
            df = pd.DataFrame([{
                'timestamp': pd.to_datetime(bar.date),
                'open': float(bar.open),
                'high': float(bar.high),
                'low': float(bar.low),
                'close': float(bar.close),
                'volume': int(bar.volume) if bar.volume != -1 else 0
            } for bar in bars])
            
            # Formulate availability_time: next day 09:00:00 (prevents look-ahead bias)
            df['availability_time'] = df['timestamp'] + pd.Timedelta(days=1) + pd.Timedelta(hours=9)
            
            # Set event dates calendar mock blackout dates for demonstration
            # In a live setup, these are fetched from earnings APIs.
            return df
        except Exception as e:
            print(f"Error fetching historical data for {symbol}: {e}")
            return pd.DataFrame()

    def fetch_macro_calendar(self) -> pd.DataFrame:
        """Fetch macro event blackout calendar schedule."""
        today = datetime.now().date()
        blackout_data = {
            'ticker': ['AAPL', 'MSFT', 'EURUSD', 'ES-202609-GLOBEX'],
            'event_date': [
                (today + timedelta(days=2)).strftime('%Y-%m-%d'),
                (today + timedelta(days=5)).strftime('%Y-%m-%d'),
                (today + timedelta(days=9)).strftime('%Y-%m-%d'), # Forex macro event
                (today + timedelta(days=12)).strftime('%Y-%m-%d'), # Future contract rollover blackout
            ],
            'event_type': ['Earnings', 'Earnings', 'Central Bank Decision', 'Rollover Week'],
            'availability_time': [
                pd.Timestamp(today),
                pd.Timestamp(today),
                pd.Timestamp(today),
                pd.Timestamp(today)
            ]
        }
        df = pd.DataFrame(blackout_data)
        df['event_date'] = pd.to_datetime(df['event_date'])
        df['availability_time'] = pd.to_datetime(df['availability_time'])
        return df
