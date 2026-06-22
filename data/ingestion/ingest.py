import os
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta

class DataIngester:
    """Acquires and caches raw market and macro calendar data."""
    
    def __init__(self, cache_dir="cache"):
        self.cache_dir = cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)

    def fetch_historical_ohlcv(self, ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
        """Fetch historical daily OHLCV bars using yfinance."""
        try:
            # yfinance returns multi-index or single-index based on query. We sanitize it.
            df = yf.download(ticker, start=start_date, end=end_date, progress=False)
            if df.empty:
                return pd.DataFrame()
            
            # Clean up column level index if present
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
                
            df = df.reset_index()
            # Standardize columns to lowercase names
            df.rename(columns={
                'Date': 'timestamp',
                'Open': 'open',
                'High': 'high',
                'Low': 'low',
                'Close': 'close',
                'Adj Close': 'adj_close',
                'Volume': 'volume'
            }, inplace=True)
            
            # Ensure timestamp is datetime
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            
            # Add availability_time. For daily bars, data is available after market close (e.g. 18:00 UTC next day or same day)
            # To be strictly PIT, availability is set to the event timestamp + 1 day at 09:00:00 (next market open)
            df['availability_time'] = df['timestamp'] + pd.Timedelta(days=1) + pd.Timedelta(hours=9)
            
            return df
        except Exception as e:
            print(f"Error fetching historical data for {ticker}: {e}")
            return pd.DataFrame()

    def fetch_macro_calendar(self) -> pd.DataFrame:
        """Fetch macro event dates and blackout dates.
        Returns a DataFrame of blackout dates."""
        # For a robust offline setup, we define a structured blackout schedule
        # that simulates event blackout dates for key symbols or markets.
        today = datetime.now().date()
        blackout_data = {
            'ticker': ['AAPL', 'MSFT', 'SPY', 'QQQ'],
            'event_date': [
                (today + timedelta(days=2)).strftime('%Y-%m-%d'),
                (today + timedelta(days=5)).strftime('%Y-%m-%d'),
                (today + timedelta(days=8)).strftime('%Y-%m-%d'),
                (today - timedelta(days=1)).strftime('%Y-%m-%d'), # Past event
            ],
            'event_type': ['Earnings', 'Earnings', 'FOMC Meeting', 'Earnings'],
            'availability_time': [
                pd.Timestamp(today),
                pd.Timestamp(today),
                pd.Timestamp(today),
                pd.Timestamp(today - timedelta(days=1)),
            ]
        }
        df = pd.DataFrame(blackout_data)
        df['event_date'] = pd.to_datetime(df['event_date'])
        df['availability_time'] = pd.to_datetime(df['availability_time'])
        return df
