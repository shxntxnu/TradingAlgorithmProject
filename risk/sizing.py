import pandas as pd
import numpy as np

class PositionSizer:
    """Calculates position sizes scaled by ATR and available equity."""
    
    def __init__(self, risk_fraction: float = 0.01, stop_atr_mult: float = 2.0):
        self.risk_fraction = risk_fraction # Risk e.g. 1% of equity per trade
        self.stop_atr_mult = stop_atr_mult # Stop loss placed at 2x ATR

    def calculate_position_size(self, 
                                equity: float, 
                                entry_price: float, 
                                atr: float, 
                                action: str) -> dict:
        """Calculate the number of shares and stop-loss price.
        Position Size = (Equity * Risk Fraction) / Stop Distance in Dollars.
        Stop Distance = stop_atr_mult * ATR.
        """
        if pd.isna(atr) or atr <= 0:
            return {'shares': 0, 'stop_loss_price': 0.0, 'risk_amount': 0.0, 'reason': 'Invalid ATR'}
            
        if entry_price <= 0:
            return {'shares': 0, 'stop_loss_price': 0.0, 'risk_amount': 0.0, 'reason': 'Invalid entry price'}
            
        risk_amount = equity * self.risk_fraction
        stop_distance = self.stop_atr_mult * atr
        
        # Calculate shares
        shares = int(np.floor(risk_amount / stop_distance))
        
        # Ensure we don't buy negative shares or exceed basic capital constraints
        if shares <= 0:
            return {'shares': 0, 'stop_loss_price': 0.0, 'risk_amount': risk_amount, 'reason': 'Calculated shares <= 0 (ATR is too high/capital too low)'}
            
        # Calculate stop loss price based on trade direction
        if action.upper() == 'BUY':
            stop_loss_price = entry_price - stop_distance
        elif action.upper() == 'SELL':
            stop_loss_price = entry_price + stop_distance
        else:
            return {'shares': 0, 'stop_loss_price': 0.0, 'risk_amount': 0.0, 'reason': 'Invalid action'}
            
        # Stop loss cannot cross 0
        stop_loss_price = max(stop_loss_price, 1e-4)
        
        return {
            'shares': shares,
            'stop_loss_price': round(stop_loss_price, 4),
            'risk_amount': risk_amount,
            'stop_distance': stop_distance,
            'position_value': shares * entry_price
        }
