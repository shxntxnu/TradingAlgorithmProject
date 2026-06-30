import os
import pandas as pd
import numpy as np
from datetime import datetime

class MultiAssetRiskControls:
    """Enforces category-level position counts and handles portfolio risk bounds (drawdowns, leverage)."""
    
    def __init__(self, 
                 max_leverage: float = 1.5,
                 max_drawdown_limit: float = 0.08,
                 lock_file_path: str = "kill_switch.lock"):
        self.max_leverage = max_leverage
        self.max_drawdown_limit = max_drawdown_limit
        self.lock_file_path = os.path.abspath(lock_file_path)
        
        # Exposure limits per asset class
        self.asset_class_limits = {
            'EQUITY': 4,
            'FOREX': 3,
            'FUTURE': 3
        }
        self.total_position_limit = 8

    def trigger_kill_switch(self, reason: str = "Manual Trigger"):
        """Write persistent lock file to halt execution."""
        timestamp = datetime.now().isoformat()
        with open(self.lock_file_path, "w") as f:
            f.write(f"ACTIVATED|{timestamp}|{reason}\n")
        print(f"!!! EMERGENCY KILL SWITCH ACTIVATED !!! Reason: {reason}")

    def is_kill_switch_active(self) -> bool:
        return os.path.exists(self.lock_file_path)

    def reset_kill_switch(self) -> bool:
        if os.path.exists(self.lock_file_path):
            os.remove(self.lock_file_path)
            print("Kill switch reset successfully.")
            return True
        return False

    def get_kill_switch_details(self) -> dict:
        """Return details of the active kill switch activation."""
        if not self.is_kill_switch_active():
            return {'active': False}
        try:
            with open(self.lock_file_path, 'r') as f:
                content = f.read().strip().split('|')
            if len(content) >= 3:
                return {'active': True, 'timestamp': content[1], 'reason': content[2]}
        except Exception:
            pass
        return {'active': True, 'timestamp': 'Unknown', 'reason': 'Lockfile exists'}

    def check_drawdown_breaker(self, equity_history: pd.Series) -> bool:
        """Check rolling peak-to-trough drawdown of equity.
        If it exceeds max_drawdown_limit, trigger the kill switch.
        """
        if len(equity_history) < 2:
            return False
            
        rolling_max = equity_history.cummax()
        # Avoid division by zero
        drawdowns = (equity_history - rolling_max) / (rolling_max + 1e-9)
        max_drawdown = drawdowns.min() # negative value
        
        if max_drawdown <= -self.max_drawdown_limit:
            reason = f"Drawdown limit reached: {max_drawdown*100:.2f}% (Limit: {-self.max_drawdown_limit*100:.2f}%)"
            self.trigger_kill_switch(reason)
            return True
            
        return False

    def get_asset_class(self, symbol: str) -> str:
        """Categorize symbol based on formatting standard."""
        symbol = symbol.upper().strip()
        if '-' in symbol:
            parts = symbol.split('-')
            if len(parts) == 3:
                return 'FUTURE'
            elif len(parts) == 2:
                return 'FOREX'
        if len(symbol) == 6 and symbol[:3] in ['EUR', 'GBP', 'USD', 'AUD', 'CAD', 'JPY']:
            return 'FOREX'
        return 'EQUITY'

    def validate_new_order(self, 
                           symbol: str, 
                           current_portfolio_value: float, 
                           current_exposure: float,
                           proposed_order_value: float,
                           active_positions: dict) -> tuple[bool, str]:
        """Verify order against leverage, total counts, and asset class limits."""
        if self.is_kill_switch_active():
            return False, "Kill switch is active"
            
        if current_portfolio_value <= 0:
            return False, "Portfolio value is zero or negative"
            
        # 1. Total leverage check
        future_exposure = current_exposure + proposed_order_value
        projected_leverage = future_exposure / current_portfolio_value
        if projected_leverage > self.max_leverage:
            return False, f"Total leverage limit exceeded: Projected {projected_leverage:.2f} > Max {self.max_leverage:.2f}"
            
        # 2. Total active positions check
        active_tickers = [t for t, qty in active_positions.items() if qty != 0]
        if symbol not in active_tickers:
            if len(active_tickers) >= self.total_position_limit:
                return False, f"Total position limit reached: {len(active_tickers)} / {self.total_position_limit}"
                
            # 3. Asset-class specific check
            asset_class = self.get_asset_class(symbol)
            limit = self.asset_class_limits.get(asset_class, 0)
            
            # Count active positions belonging to this asset class
            class_count = sum(1 for t in active_tickers if self.get_asset_class(t) == asset_class)
            if class_count >= limit:
                return False, f"Asset class limit for {asset_class} reached: {class_count} / {limit}"
                
        return True, "Approved"


class MultiAssetSizer:
    """Calculates position sizes accounting for leverage and asset multipliers."""
    
    def __init__(self, stop_atr_mult: float = 2.0):
        self.stop_atr_mult = stop_atr_mult
        
        # Risk fraction per asset class (tighter rules for Forex and Futures due to leverage)
        self.risk_fractions = {
            'EQUITY': 0.01,   # 1% per trade
            'FOREX': 0.005,   # 0.5% per trade
            'FUTURE': 0.005   # 0.5% per trade
        }

    def get_contract_multiplier(self, symbol: str) -> float:
        """Returns standard exchange multipliers for leverage adjustments.
        - Equity / Forex multiplier: 1
        - Futures multipliers: ES (50), NQ (20), CL (1000), GC (100)
        """
        symbol = symbol.upper().strip()
        if symbol.startswith('ES'):
            return 50.0 # E-mini S&P (50 USD per index point)
        elif symbol.startswith('NQ'):
            return 20.0 # E-mini Nasdaq (20 USD per index point)
        elif symbol.startswith('CL'):
            return 1000.0 # Crude Oil (1000 USD per dollar price change)
        elif symbol.startswith('GC'):
            return 100.0 # Gold Futures (100 USD per dollar price change)
        return 1.0

    def get_asset_class(self, symbol: str) -> str:
        symbol = symbol.upper().strip()
        if '-' in symbol:
            parts = symbol.split('-')
            if len(parts) == 3:
                return 'FUTURE'
            elif len(parts) == 2:
                return 'FOREX'
        if len(symbol) == 6 and symbol[:3] in ['EUR', 'GBP', 'USD', 'AUD', 'CAD', 'JPY']:
            return 'FOREX'
        return 'EQUITY'

    def calculate_size(self, 
                       symbol: str, 
                       equity: float, 
                       entry_price: float, 
                       atr: float, 
                       action: str) -> dict:
        """Calculate shares/contracts and stop-loss price.
        Formula:
        Size = (Equity * Risk Fraction) / (Stop Distance * Contract Multiplier)
        """
        if pd.isna(atr) or atr <= 0 or entry_price <= 0:
            return {'shares': 0, 'stop_loss_price': 0.0, 'reason': 'Invalid pricing/ATR'}
            
        asset_class = self.get_asset_class(symbol)
        risk_frac = self.risk_fractions.get(asset_class, 0.005)
        multiplier = self.get_contract_multiplier(symbol)
        
        risk_amount = equity * risk_frac
        stop_distance = self.stop_atr_mult * atr
        
        # Sizing formula incorporating multiplier (e.g. 50x for ES)
        stop_distance_val = stop_distance * multiplier
        shares = int(np.floor(risk_amount / stop_distance_val))
        
        if shares <= 0:
            return {
                'shares': 0, 
                'stop_loss_price': 0.0, 
                'reason': f'Calculated size <= 0 (ATR {atr:.4f} is too high / risk allocation {risk_amount:.2f} too low)'
            }
            
        # Stop loss price
        if action.upper() == 'BUY':
            stop_loss_price = entry_price - stop_distance
        elif action.upper() == 'SELL':
            stop_loss_price = entry_price + stop_distance
        else:
            return {'shares': 0, 'stop_loss_price': 0.0, 'reason': 'Invalid trade action'}
            
        stop_loss_price = max(stop_loss_price, 1e-4)
        
        # Calculate nominal value of position
        # For stocks: shares * price
        # For FX: shares * price * multiplier
        # For Futures: contracts * price * multiplier
        nominal_value = shares * entry_price * multiplier
        
        return {
            'shares': shares,
            'stop_loss_price': round(stop_loss_price, 4),
            'risk_amount': risk_amount,
            'stop_distance': stop_distance,
            'position_value': nominal_value
        }
