import pandas as pd
from datetime import datetime, timedelta

class SignalGenerator:
    """Generates trade signals from model direction probabilities and factor filters,
    applying universe and calendar event blackout rules.
    """
    
    def __init__(self, confidence_threshold: float = 0.55, blackout_window_days: int = 3):
        self.confidence_threshold = confidence_threshold
        self.blackout_window_days = blackout_window_days

    def filter_blackout_dates(self, ticker: str, current_time: datetime, blackout_df: pd.DataFrame) -> bool:
        """Return True if the current_time falls inside a calendar event blackout window
        for the given ticker.
        """
        if blackout_df is None or blackout_df.empty:
            return False
            
        # Select blackouts for this ticker or macro (SPY, FOMC)
        ticker_blackouts = blackout_df[
            (blackout_df['ticker'] == ticker) | 
            (blackout_df['ticker'].isin(['SPY', 'QQQ', 'FOMC']))
        ]
        
        if ticker_blackouts.empty:
            return False
            
        current_date = pd.to_datetime(current_time).date()
        
        for _, row in ticker_blackouts.iterrows():
            event_date = pd.to_datetime(row['event_date']).date()
            start_blackout = event_date - timedelta(days=self.blackout_window_days)
            end_blackout = event_date + timedelta(days=self.blackout_window_days)
            
            if start_blackout <= current_date <= end_blackout:
                # Event falls within holding window
                return True
                
        return False

    def generate_signals(self, 
                         ticker: str,
                         df: pd.DataFrame, 
                         direction_probs: pd.Series, 
                         factor_filter_results: dict,
                         current_time: datetime, 
                         blackout_df: pd.DataFrame = None) -> dict:
        """Evaluate the latest bar of a ticker and generate trade signals.
        Returns a dict indicating if a trade is recommended and associated metadata.
        """
        if df.empty or direction_probs.empty:
            return {'action': 'HOLD', 'confidence': 0.0, 'reason': 'No data'}
            
        latest_idx = df.index[-1]
        latest_price = df.loc[latest_idx, 'close']
        latest_prob = direction_probs.loc[latest_idx]
        
        # 1. Universe check (e.g. check average volume is liquid enough)
        if 'relative_volume' in df.columns:
            avg_volume = df['volume'].rolling(20).mean().iloc[-1]
            # Assure minimum daily liquidity (e.g. 50,000 shares for small-scale simulation)
            if pd.isna(avg_volume) or avg_volume < 50000:
                return {
                    'action': 'HOLD',
                    'confidence': latest_prob,
                    'reason': f'Low liquidity: avg volume {avg_volume}'
                }
                
        # 2. Blackout check
        if self.filter_blackout_dates(ticker, current_time, blackout_df):
            return {
                'action': 'HOLD',
                'confidence': latest_prob,
                'reason': 'Event blackout active (Earnings/Macro)'
            }
            
        # 3. Factor Exposure Check (Model C filter)
        if factor_filter_results.get('is_rejected', False):
            return {
                'action': 'HOLD',
                'confidence': latest_prob,
                'reason': f"Factor filter rejected: {factor_filter_results.get('reason', 'Unknown')}"
            }
            
        # 4. Confidence Threshold Check (Model A prediction)
        if latest_prob >= self.confidence_threshold:
            return {
                'action': 'BUY',
                'price': latest_price,
                'confidence': latest_prob,
                'reason': f"Signal strength {latest_prob:.2f} >= threshold"
            }
        elif latest_prob <= (1 - self.confidence_threshold):
            return {
                'action': 'SELL',
                'price': latest_price,
                'confidence': latest_prob,
                'reason': f"Signal weakness {latest_prob:.2f} <= threshold"
            }
            
        return {
            'action': 'HOLD',
            'confidence': latest_prob,
            'reason': f"Probability {latest_prob:.2f} is neutral"
        }
