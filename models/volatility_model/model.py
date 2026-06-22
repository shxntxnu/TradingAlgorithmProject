import numpy as np
import pandas as pd
from scipy.optimize import minimize

class VolatilityModel:
    """Forecasts forward volatility per instrument using a custom GARCH(1,1) optimizer or EWMA fallback."""
    
    def __init__(self, fallback_window: int = 20):
        self.fallback_window = fallback_window
        # Initial parameters for GARCH(1,1): variance = omega + alpha * r_{t-1}^2 + beta * var_{t-1}
        self.omega = 1e-6
        self.alpha = 0.05
        self.beta = 0.90
        self.is_fitted = False

    def _garch_likelihood(self, params, returns):
        omega, alpha, beta = params
        # Constraints: parameters must be positive and stable
        if omega <= 1e-10 or alpha < 0 or beta < 0 or (alpha + beta) >= 0.999:
            return 1e15
            
        n = len(returns)
        variance = np.zeros(n)
        # Seed initial variance with sample variance of returns
        variance[0] = max(np.var(returns), 1e-8)
        
        for t in range(1, n):
            variance[t] = omega + alpha * (returns[t-1]**2) + beta * variance[t-1]
            
        # Log likelihood of standard normal distributions
        log_lik = -0.5 * np.sum(np.log(2 * np.pi * variance) + (returns**2) / variance)
        return -log_lik # Return negative log likelihood to minimize

    def fit(self, returns: pd.Series):
        """Fit GARCH(1,1) parameters on historical return series."""
        # Standardize returns to make optimizer stable
        r = returns.dropna().values
        if len(r) < 30:
            self.is_fitted = False
            return False
            
        initial_params = [1e-6, 0.05, 0.90]
        bounds = ((1e-12, 1e-3), (1e-4, 0.3), (0.5, 0.98))
        
        try:
            res = minimize(
                self._garch_likelihood,
                initial_params,
                args=(r,),
                bounds=bounds,
                method='L-BFGS-B'
            )
            if res.success:
                self.omega, self.alpha, self.beta = res.x
                self.is_fitted = True
                return True
        except Exception as e:
            print(f"GARCH optimization failed: {e}. Falling back to EWMA/Rolling volatility.")
            
        self.is_fitted = False
        return False

    def forecast_volatility(self, returns: pd.Series) -> float:
        """Forecast volatility for the next step.
        Returns annualized volatility forecast (as standard deviation).
        """
        r = returns.dropna().values
        if len(r) < 5:
            return 0.20 # Fallback to standard 20% volatility
            
        if self.is_fitted:
            # Reconstruct variance series to get the last step variance
            n = len(r)
            variance = np.zeros(n)
            variance[0] = max(np.var(r), 1e-8)
            for t in range(1, n):
                variance[t] = self.omega + self.alpha * (r[t-1]**2) + self.beta * variance[t-1]
                
            # Forecast for next step (t+1)
            next_var = self.omega + self.alpha * (r[-1]**2) + self.beta * variance[-1]
            # Annualize (assuming daily bars: sqrt(252))
            ann_vol = np.sqrt(next_var) * np.sqrt(252)
            return float(ann_vol)
        else:
            # Fallback: rolling standard deviation annualized
            roll_std = returns.tail(self.fallback_window).std()
            if pd.isna(roll_std) or roll_std <= 0:
                return 0.20
            return float(roll_std * np.sqrt(252))
