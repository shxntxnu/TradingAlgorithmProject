import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier

class DirectionModel:
    """Predicts the probability of a positive forward N-day return."""
    
    def __init__(self, forward_window: int = 5, model=None):
        self.forward_window = forward_window
        self.feature_cols = [
            'ret_1d', 'ret_5d', 'ret_10d', 'momentum_20d', 'rsi_14', 'ma_crossover',
            'atr_pct', 'realized_vol_20d', 'relative_volume', 'vwap_dev_20',
            'relative_strength_5d', 'beta_60d'
        ]
        # Use GradientBoostingClassifier as the core robustness-first model
        self.model = model or GradientBoostingClassifier(
            n_estimators=100,
            max_depth=3,
            learning_rate=0.05,
            random_state=42
        )
        self.is_fitted = False

    def prepare_training_data(self, df: pd.DataFrame):
        """Prepare target variable and features.
        Target is 1 if close in N days is higher than close today, else 0.
        Drops last N rows since future return is unknown.
        """
        if len(df) <= self.forward_window:
            return None, None
            
        df = df.sort_values('timestamp').copy()
        
        # Calculate target: 1 if close shifted by -forward_window is higher than close
        future_close = df['close'].shift(-self.forward_window)
        target = (future_close > df['close']).astype(int)
        
        # Features and target alignment
        X = df[self.feature_cols].copy()
        y = target
        
        # Drop the last N rows where future target is NaN
        X = X.iloc[:-self.forward_window]
        y = y.iloc[:-self.forward_window]
        
        # Handle any residual NaNs safely
        valid_idx = X.notna().all(axis=1) & y.notna()
        return X[valid_idx], y[valid_idx]

    def fit(self, df: pd.DataFrame):
        """Train the direction model."""
        X, y = self.prepare_training_data(df)
        if X is None or len(X) < 20:
            print("Insufficient data to train DirectionModel")
            return False
            
        self.model.fit(X, y)
        self.is_fitted = True
        return True

    def predict_probability(self, df: pd.DataFrame) -> pd.Series:
        """Predict the probability of positive return for the current state.
        Uses only the latest row's features (no look-ahead).
        """
        if not self.is_fitted:
            # Fallback to neutral 0.5 probability if model isn't trained
            return pd.Series(0.5, index=df.index)
            
        X = df[self.feature_cols].copy()
        
        # GradientBoosting predict_proba returns [P(0), P(1)]
        probs = self.model.predict_proba(X)[:, 1]
        return pd.Series(probs, index=df.index)
