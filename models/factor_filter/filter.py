import pandas as pd
import numpy as np
import statsmodels.api as sm

class FactorFilter:
    """Rejects or down-weights trades whose return is indistinguishable from market beta."""
    
    def __init__(self, p_value_threshold: float = 0.05, max_beta: float = 2.0):
        self.p_value_threshold = p_value_threshold
        self.max_beta = max_beta

    def analyze_exposure(self, ticker_returns: pd.Series, index_returns: pd.Series) -> dict:
        """Regress ticker returns against index returns.
        Returns regression stats and a decision on whether to reject the trade.
        """
        # Ensure alignment
        data = pd.DataFrame({
            'ticker': ticker_returns,
            'index': index_returns
        }).dropna()
        
        # We need a minimum number of observations to run regression
        if len(data) < 30:
            return {
                'alpha': 0.0,
                'beta': 1.0,
                'p_value_alpha': 1.0,
                'is_rejected': True,
                'reason': 'Insufficient history'
            }
            
        y = data['ticker']
        X = sm.add_constant(data['index'])
        
        try:
            res = sm.OLS(y, X).fit()
            alpha = res.params.get('const', 0.0)
            beta = res.params.get('index', 1.0)
            p_value_alpha = res.pvalues.get('const', 1.0)
            
            is_rejected = False
            reason = 'Pass'
            
            # Reject if beta exceeds leverage/risk guidelines
            if abs(beta) > self.max_beta:
                is_rejected = True
                reason = f'Beta {beta:.2f} exceeds cap {self.max_beta:.2f}'
            # Reject if alpha is negative or close to zero
            elif alpha <= 0:
                is_rejected = True
                reason = f'Negative alpha ({alpha:.6f})'
            # Reject if alpha is statistically indistinguishable from zero
            elif p_value_alpha > self.p_value_threshold:
                is_rejected = True
                reason = f'Insignificant alpha p-val: {p_value_alpha:.3f} > {self.p_value_threshold}'
                
            return {
                'alpha': float(alpha),
                'beta': float(beta),
                'p_value_alpha': float(p_value_alpha),
                'is_rejected': is_rejected,
                'reason': reason
            }
        except Exception as e:
            return {
                'alpha': 0.0,
                'beta': 1.0,
                'p_value_alpha': 1.0,
                'is_rejected': True,
                'reason': f'Regression error: {e}'
            }
        
    def should_reject_trade(self, ticker_returns: pd.Series, index_returns: pd.Series) -> bool:
        """Helper to quickly check if trade should be filtered out."""
        result = self.analyze_exposure(ticker_returns, index_returns)
        return result['is_rejected']
