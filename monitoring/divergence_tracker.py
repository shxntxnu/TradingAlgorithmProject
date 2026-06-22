import pandas as pd
import numpy as np

class DivergenceTracker:
    """Compares real-time execution results against backtest predictions
    to catch model decay, execution slippage, or data feed mismatch.
    """
    
    def __init__(self, max_allowed_divergence: float = 0.05):
        self.max_allowed_divergence = max_allowed_divergence # e.g. 5% underperformance

    def calculate_tracking_metrics(self, 
                                   live_equity: pd.Series, 
                                   backtest_equity: pd.Series) -> dict:
        """Compare the cumulative returns of live vs backtest.
        Returns a dict of metrics and warning flags.
        """
        if len(live_equity) < 5 or len(backtest_equity) < 5:
            return {
                'divergence': 0.0,
                'correlation': 1.0,
                'is_divergent': False,
                'reason': 'Insufficient history to compare'
            }
            
        # Calculate returns
        live_rets = live_equity.pct_change().dropna()
        bt_rets = backtest_equity.pct_change().dropna()
        
        # Cumulative returns
        cum_live = float((1 + live_rets).prod() - 1)
        cum_bt = float((1 + bt_rets).prod() - 1)
        
        divergence = cum_bt - cum_live
        
        # Align returns to calculate daily correlation
        df_merged = pd.DataFrame({
            'live': live_rets,
            'backtest': bt_rets
        }).dropna()
        
        correlation = 1.0
        if len(df_merged) >= 5:
            correlation = float(df_merged['live'].corr(df_merged['backtest']))
            if np.isnan(correlation):
                correlation = 0.0
                
        is_divergent = False
        reason = "Tracking is within acceptable limits"
        
        # Flag if live is underperforming backtest by too much
        if divergence > self.max_allowed_divergence:
            is_divergent = True
            reason = (f"Significant underperformance: Live ({cum_live*100:.2f}%) "
                      f"trails Backtest ({cum_bt*100:.2f}%) by {divergence*100:.2f}%")
        # Flag if performance returns are completely decorrelated
        elif correlation < 0.20 and len(df_merged) >= 10:
            is_divergent = True
            reason = f"Poor return correlation: {correlation:.2f} (Model or data drift suspected)"
            
        return {
            'live_return': cum_live,
            'backtest_return': cum_bt,
            'divergence': divergence,
            'correlation': correlation,
            'is_divergent': is_divergent,
            'reason': reason
        }
