import os
import sys
import asyncio

# Resolve Windows ProactorEventLoop signal set_wakeup_fd issues before importing ibkr_client
if sys.platform == 'win32':
    try:
        if not isinstance(asyncio.get_event_loop_policy(), asyncio.WindowsSelectorEventLoopPolicy):
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except AttributeError:
        pass

import unittest
import tempfile
import pandas as pd
from unittest.mock import MagicMock

from risk.controls import RiskControls
from risk.sizing import PositionSizer
from execution.ibkr_client import IBKRClient

class TestRiskControls(unittest.TestCase):
    """Test suite to verify risk controls, bracket orders, and the Kill Switch in isolation."""
    
    def setUp(self):
        # Create a temporary lock file path
        self.lock_dir = tempfile.TemporaryDirectory()
        self.lock_file = os.path.join(self.lock_dir.name, "kill_switch.lock")
        
        self.risk_ctrl = RiskControls(
            max_leverage=1.5,
            max_drawdown_limit=0.08,
            max_single_name_pct=0.20,
            lock_file_path=self.lock_file
        )
        
        # Sizer with 1% risk fraction and 2x ATR stop distance
        self.sizer = PositionSizer(risk_fraction=0.01, stop_atr_mult=2.0)

    def tearDown(self):
        self.lock_dir.cleanup()

    def test_position_sizing_and_stop_loss(self):
        """Verify position sizing calculations and correct standing stop-loss price placement."""
        equity = 100000.0
        entry_price = 100.0
        atr = 2.5 # 2.5 ATR
        
        # Risk amount is 100000 * 0.01 = 1000.
        # Stop distance is 2 * 2.5 = 5.0.
        # Shares = 1000 / 5 = 200 shares.
        # Stop loss price for BUY = 100.0 - 5.0 = 95.0.
        
        res_buy = self.sizer.calculate_position_size(equity, entry_price, atr, 'BUY')
        self.assertEqual(res_buy['shares'], 200)
        self.assertEqual(res_buy['stop_loss_price'], 95.0)
        
        # Stop loss price for SELL = 100.0 + 5.0 = 105.0.
        res_sell = self.sizer.calculate_position_size(equity, entry_price, atr, 'SELL')
        self.assertEqual(res_sell['shares'], 200)
        self.assertEqual(res_sell['stop_loss_price'], 105.0)

    def test_drawdown_circuit_breaker(self):
        """Verify that breaching the drawdown limit triggers the persistent Kill Switch."""
        # Equity curve starting at 100k, peaking at 105k, and dropping to 96k (9k drawdown = ~8.57% from peak)
        equity_history = pd.Series([100000.0, 105000.0, 102000.0, 96000.0])
        
        # Before check, kill switch is inactive
        self.assertFalse(self.risk_ctrl.is_kill_switch_active())
        
        # Check drawdown breaker
        triggered = self.risk_ctrl.check_drawdown_breaker(equity_history)
        
        # Must return True (breaker hit) and activate persistent kill switch
        self.assertTrue(triggered)
        self.assertTrue(self.risk_ctrl.is_kill_switch_active())
        
        # Verify the details in the lock file
        details = self.risk_ctrl.get_kill_switch_details()
        self.assertTrue(details['active'])
        self.assertIn("Drawdown limit reached", details['reason'])

    def test_kill_switch_isolation(self):
        """Verify that when the kill switch is triggered, all open orders are cancelled,
        positions are flattened, and any new order placement is blocked.
        """
        # Create a client in dry-run mode for isolation testing
        client = IBKRClient(dry_run=True)
        
        # Manually add some mock orders and positions
        client.mock_positions['AAPL'] = {'shares': 100, 'entry_price': 170.0, 'stop_loss_price': 160.0}
        client.mock_orders.append({'order_id': 1001, 'ticker': 'AAPL', 'status': 'Submitted'})
        
        # Check initial state
        self.assertEqual(len(client.get_positions()), 1)
        self.assertFalse(self.risk_ctrl.is_kill_switch_active())
        
        # Trigger flatten and kill
        success = client.flatten_positions_and_kill(self.risk_ctrl)
        
        # Assert success and state shifts
        self.assertTrue(success)
        self.assertTrue(self.risk_ctrl.is_kill_switch_active())
        
        # Verify mock client state: positions flattened, open orders cancelled
        self.assertEqual(len(client.get_positions()), 0)
        open_orders = [o for o in client.mock_orders if o['status'] != 'Cancelled' and o['status'] != 'Filled']
        self.assertEqual(len(open_orders), 0)
        
        # Check that new order validation rejects orders
        allowed, reason = self.risk_ctrl.validate_proposed_order(
            current_portfolio_value=100000.0,
            current_exposure=0.0,
            proposed_order_value=5000.0
        )
        self.assertFalse(allowed)
        self.assertIn("Kill switch is active", reason)
        
        # Reset and check that order entry is re-enabled
        self.risk_ctrl.reset_kill_switch()
        self.assertFalse(self.risk_ctrl.is_kill_switch_active())
        
        allowed_after_reset, _ = self.risk_ctrl.validate_proposed_order(
            current_portfolio_value=100000.0,
            current_exposure=0.0,
            proposed_order_value=5000.0
        )
        self.assertTrue(allowed_after_reset)

if __name__ == '__main__':
    unittest.main()
