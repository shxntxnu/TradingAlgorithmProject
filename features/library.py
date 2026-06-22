import pandas as pd
import numpy as np

def compute_atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    """Compute Average True Range (ATR)."""
    close_prev = df['close'].shift(1)
    tr1 = df['high'] - df['low']
    tr2 = (df['high'] - close_prev).abs()
    tr3 = (df['low'] - close_prev).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=window, min_periods=1).mean()
    return atr

def compute_rsi(df: pd.DataFrame, window: int = 14) -> pd.Series:
    """Compute Relative Strength Index (RSI)."""
    delta = df['close'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    
    avg_gain = gain.rolling(window=window, min_periods=1).mean()
    avg_loss = loss.rolling(window=window, min_periods=1).mean()
    
    rs = avg_gain / (avg_loss + 1e-9)
    rsi = 100 - (100 / (1 + rs))
    return rsi

def compute_features(df: pd.DataFrame, index_df: pd.DataFrame = None) -> pd.DataFrame:
    """Computes features for a single ticker's daily ohlcv.
    Ensures no look-ahead bias.
    """
    if df.empty:
        return df
        
    df = df.sort_values('timestamp').copy()
    
    # 1. Price-based features
    df['ret_1d'] = df['close'].pct_change(1)
    df['ret_5d'] = df['close'].pct_change(5)
    df['ret_10d'] = df['close'].pct_change(10)
    df['momentum_20d'] = df['close'].pct_change(20)
    
    # RSI
    df['rsi_14'] = compute_rsi(df, window=14)
    
    # Moving Average Crossover (5-day / 20-day SMA ratio)
    sma_5 = df['close'].rolling(5, min_periods=1).mean()
    sma_20 = df['close'].rolling(20, min_periods=1).mean()
    df['ma_crossover'] = sma_5 / (sma_20 + 1e-9)
    
    # ATR realized volatility
    df['atr_14'] = compute_atr(df, window=14)
    df['atr_pct'] = df['atr_14'] / (df['close'] + 1e-9)
    df['realized_vol_20d'] = df['ret_1d'].rolling(20, min_periods=1).std()
    
    # 2. Volume-based features
    vol_sma_20 = df['volume'].rolling(20, min_periods=1).mean()
    df['relative_volume'] = df['volume'] / (vol_sma_20 + 1e-9)
    
    # VWAP deviation (daily VWAP approximation for daily bars: rolling volume-weighted close)
    cum_vol_price = (df['close'] * df['volume']).rolling(20, min_periods=1).sum()
    cum_vol = df['volume'].rolling(20, min_periods=1).sum()
    vwap_20 = cum_vol_price / (cum_vol + 1e-9)
    df['vwap_dev_20'] = (df['close'] - vwap_20) / (vwap_20 + 1e-9)
    
    # 3. Cross-sectional and Factor Exposure vs Index (e.g. SPY)
    if index_df is not None and not index_df.empty:
        idx_df = index_df.sort_values('timestamp')[['timestamp', 'close']].copy()
        idx_df.rename(columns={'close': 'index_close'}, inplace=True)
        idx_df['index_ret_1d'] = idx_df['index_close'].pct_change(1)
        
        # Merge data to line up timestamps
        merged = pd.merge_asof(df, idx_df, on='timestamp')
        
        # Relative strength vs index
        merged['relative_strength_5d'] = merged['ret_5d'] - merged['index_close'].pct_change(5)
        
        # Rolling index beta (Fama-French loading proxy)
        # beta = Cov(R_i, R_m) / Var(R_m)
        rolling_cov = merged['ret_1d'].rolling(60, min_periods=10).cov(merged['index_ret_1d'])
        rolling_var = merged['index_ret_1d'].rolling(60, min_periods=10).var()
        merged['beta_60d'] = rolling_cov / (rolling_var + 1e-9)
        merged['beta_60d'] = merged['beta_60d'].fillna(1.0) # Fallback to market beta = 1.0
        
        df = merged
    else:
        df['relative_strength_5d'] = df['ret_5d']
        df['beta_60d'] = 1.0
        
    # Forward fill then backfill NaNs to avoid missing values in model
    feature_cols = [
        'ret_1d', 'ret_5d', 'ret_10d', 'momentum_20d', 'rsi_14', 'ma_crossover',
        'atr_14', 'atr_pct', 'realized_vol_20d', 'relative_volume', 'vwap_dev_20',
        'relative_strength_5d', 'beta_60d'
    ]
    df[feature_cols] = df[feature_cols].ffill().bfill().fillna(0.0)
    
    return df
