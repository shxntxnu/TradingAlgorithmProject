import os
import pandas as pd
from datetime import datetime

class LocalParquetStore:
    """Manages Parquet-based data persistence and versioning with point-in-time filtering."""
    
    def __init__(self, root_dir="data_store"):
        self.root_dir = os.path.abspath(root_dir)
        os.makedirs(self.root_dir, exist_ok=True)

    def get_path(self, ticker: str, category: str, version: str = None) -> str:
        if version:
            return os.path.join(self.root_dir, category, version, f"{ticker}.csv")
        return os.path.join(self.root_dir, category, f"{ticker}.csv")

    def save_data(self, ticker: str, category: str, df: pd.DataFrame, version: str = None):
        """Save dataframe as CSV, stamping availability_time if missing."""
        if df.empty:
            return
            
        df = df.copy()
        if 'availability_time' not in df.columns:
            df['availability_time'] = pd.Timestamp.now()
            
        # Ensure availability_time and timestamp are in datetime format
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['availability_time'] = pd.to_datetime(df['availability_time'])
        
        path = self.get_path(ticker, category, version)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        df.to_csv(path, index=False)

    def load_data(self, ticker: str, category: str, version: str = None) -> pd.DataFrame:
        """Load full raw data from CSV."""
        path = self.get_path(ticker, category, version)
        if not os.path.exists(path):
            return pd.DataFrame()
        df = pd.read_csv(path)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['availability_time'] = pd.to_datetime(df['availability_time'])
        return df

    def load_data_as_of(self, ticker: str, category: str, decision_time: datetime, version: str = None) -> pd.DataFrame:
        """Load data containing only observations available on or before decision_time.
        Prevents look-ahead bias in simulation and production decision-making.
        """
        df = self.load_data(ticker, category, version)
        if df.empty:
            return df
            
        decision_dt = pd.to_datetime(decision_time)
        
        # Check if availability_time is timezone-aware or naive and align them
        if df['availability_time'].dt.tz is not None and decision_dt.tzinfo is None:
            decision_dt = decision_dt.tz_localize(df['availability_time'].dt.tz)
        elif df['availability_time'].dt.tz is None and decision_dt.tzinfo is not None:
            decision_dt = decision_dt.tz_localize(None)
            
        filtered_df = df[df['availability_time'] <= decision_dt].copy()
        return filtered_df
