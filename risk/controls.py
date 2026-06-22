import os
import pandas as pd
from datetime import datetime

class RiskControls:
    """Enforces portfolio-level risk limits, including drawdowns, leverage, concentration, and the Kill Switch."""
    
    def __init__(self, 
                 max_leverage: float = 1.5, 
                 max_drawdown_limit: float = 0.08, 
                 max_single_name_pct: float = 0.15,
                 lock_file_path: str = "kill_switch.lock"):
        self.max_leverage = max_leverage
        self.max_drawdown_limit = max_drawdown_limit
        self.max_single_name_pct = max_single_name_pct
        self.lock_file_path = os.path.abspath(lock_file_path)

    def trigger_kill_switch(self, reason: str = "Manual Trigger"):
        """Activate the kill switch persistently by writing a lock file."""
        timestamp = datetime.now().isoformat()
        with open(self.lock_file_path, "w") as f:
            f.write(f"ACTIVATED|{timestamp}|{reason}\n")
        print(f"!!! KILL SWITCH ACTIVATED !!! Reason: {reason}")

    def reset_kill_switch(self) -> bool:
        """Reset the kill switch by removing the lock file."""
        if os.path.exists(self.lock_file_path):
            os.remove(self.lock_file_path)
            print("Kill switch reset successfully.")
            return True
        return False

    def is_kill_switch_active(self) -> bool:
        """Check if the persistent kill switch lock file is present."""
        return os.path.exists(self.lock_file_path)
        
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

    def validate_proposed_order(self, 
                                current_portfolio_value: float, 
                                current_exposure: float, 
                                proposed_order_value: float,
                                current_ticker_exposure: float = 0.0) -> tuple[bool, str]:
        """Validate if a proposed order violates leverage, concentration or kill switch restrictions."""
        if self.is_kill_switch_active():
            return False, "Kill switch is active. No orders permitted."
            
        if current_portfolio_value <= 0:
            return False, "Portfolio value is zero or negative."
            
        # 1. Leverage check
        future_exposure = current_exposure + proposed_order_value
        projected_leverage = future_exposure / current_portfolio_value
        if projected_leverage > self.max_leverage:
            return False, f"Leverage limit exceeded: Projected {projected_leverage:.2f} > Max {self.max_leverage:.2f}"
            
        # 2. Single-name concentration check
        future_ticker_exposure = current_ticker_exposure + proposed_order_value
        projected_ticker_weight = future_ticker_exposure / current_portfolio_value
        if projected_ticker_weight > self.max_single_name_pct:
            return False, f"Single-name weight exceeded: Projected {projected_ticker_weight*100:.1f}% > Max {self.max_single_name_pct*100:.1f}%"
            
        return True, "Approved"
