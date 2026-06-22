import pandas as pd

def validate_ohlcv_schema(df: pd.DataFrame) -> bool:
    """Validate schema, price bounds, volume bounds, and timestamp duplicates."""
    if df is None or df.empty:
        print("Validation warning: Dataframe is empty or None")
        return False
        
    required_cols = {'timestamp', 'open', 'high', 'low', 'close', 'volume', 'availability_time'}
    if not required_cols.issubset(df.columns):
        print(f"Validation failed: Missing columns. Required: {required_cols}. Got: {set(df.columns)}")
        return False
        
    # Check value ranges
    price_cols = ['open', 'high', 'low', 'close']
    for col in price_cols:
        if (df[col] <= 0).any():
            print(f"Validation failed: Found prices <= 0 in '{col}' column.")
            return False
            
    if (df['volume'] < 0).any():
        print("Validation failed: Found negative volumes.")
        return False
        
    # Check timestamp duplicates
    if df['timestamp'].duplicated().any():
        print("Validation failed: Duplicate event timestamps found.")
        return False
        
    return True

def check_pit_integrity(df: pd.DataFrame) -> bool:
    """Verify that availability_time is always greater than or equal to the event timestamp.
    If availability_time is prior to event time, look-ahead bias is occurring.
    """
    if df is None or df.empty:
        return True
        
    event_times = pd.to_datetime(df['timestamp']).dt.tz_localize(None)
    avail_times = pd.to_datetime(df['availability_time']).dt.tz_localize(None)
    
    violations = event_times > avail_times
    if violations.any():
        print(f"Validation failed: Point-in-Time integrity violation. "
              f"Availability time is prior to event time in {violations.sum()} rows.")
        return False
        
    return True
