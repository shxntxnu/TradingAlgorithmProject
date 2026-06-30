import os
import sys
import asyncio

# Resolve Windows ProactorEventLoop signal set_wakeup_fd issues before importing ib_insync
if sys.platform == 'win32':
    try:
        if not isinstance(asyncio.get_event_loop_policy(), asyncio.WindowsSelectorEventLoopPolicy):
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except AttributeError:
        pass

import time
import json
from datetime import datetime
from ib_insync import IB, Stock, LimitOrder, StopOrder, MarketOrder

class IBKRClient:
    """Manages Interactive Brokers API session, order placement (with bracket stop-losses),
    and the emergency position flattening (kill switch). Supports dry_run/mock fallback.
    """
    
    def __init__(self, host: str = '127.0.0.1', port: int = 7497, client_id: int = 1, dry_run: bool = True):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.dry_run = dry_run
        
        self.ib = IB()
        self.is_connected = False
        
        # Mock portfolio for dry-run mode
        self.mock_equity = 100000.0
        self.mock_positions = {} # ticker -> {'shares': float, 'entry_price': float, 'stop_loss_price': float}
        self.mock_orders = [] # list of dicts
        self.mock_order_id_counter = 1000

    def connect(self) -> bool:
        """Connect to IB TWS or Gateway, or fall back to dry run if connection fails or if dry_run=True."""
        if self.dry_run:
            print("Running in DRY RUN (Mock) mode. Connection to TWS bypassed.")
            self.is_connected = True
            return True
            
        try:
            self.ib.connect(self.host, self.port, clientId=self.client_id)
            self.is_connected = True
            print(f"Connected to IBKR at {self.host}:{self.port}")
            return True
        except Exception as e:
            print(f"IBKR connection failed: {e}. Falling back to DRY RUN (Mock) mode.")
            self.dry_run = True
            self.is_connected = True
            return True

    def disconnect(self):
        """Disconnect from TWS/Gateway."""
        if self.ib.isConnected():
            self.ib.disconnect()
            self.is_connected = False
            print("Disconnected from IBKR.")

    def get_equity(self) -> float:
        """Get total account equity."""
        if self.dry_run:
            return self.mock_equity
            
        try:
            # Fetch account summary
            for item in self.ib.accountSummary():
                if item.tag == 'NetLiquidation':
                    return float(item.value)
        except Exception as e:
            print(f"Error fetching real account equity: {e}")
            
        return self.mock_equity # Fallback to mock

    def get_positions(self) -> dict:
        """Get dict of current positions: ticker -> shares."""
        if self.dry_run:
            return {t: pos['shares'] for t, pos in self.mock_positions.items() if pos['shares'] != 0}
            
        positions = {}
        try:
            for p in self.ib.positions():
                ticker = p.contract.symbol
                positions[ticker] = p.position
        except Exception as e:
            print(f"Error fetching IB positions: {e}")
            
        return positions

    def place_bracket_order(self, 
                            ticker: str, 
                            action: str, 
                            shares: int, 
                            limit_price: float, 
                            stop_loss_price: float) -> list:
        """Submit a bracket order to IBKR:
        1. Limit order for entry (with transmit=False)
        2. Stop order for stop-loss (with transmit=True, parentId linked)
        This places the stop-loss order directly on the broker's books.
        """
        action = action.upper()
        if shares <= 0:
            return []
            
        if self.dry_run:
            self.mock_order_id_counter += 1
            parent_id = self.mock_order_id_counter
            stop_id = parent_id + 1
            
            # Simulate immediate entry fill in mock mode
            self.mock_positions[ticker] = {
                'shares': shares if action == 'BUY' else -shares,
                'entry_price': limit_price,
                'stop_loss_price': stop_loss_price
            }
            
            # Record order
            order_record = {
                'order_id': parent_id,
                'ticker': ticker,
                'action': action,
                'shares': shares,
                'type': 'LMT',
                'price': limit_price,
                'stop_loss': stop_loss_price,
                'status': 'Filled',
                'timestamp': datetime.now().isoformat()
            }
            self.mock_orders.append(order_record)
            print(f"[DRY RUN] Filled Bracket Order for {ticker}: {action} {shares} shares @ {limit_price}. Standing Stop-Loss @ {stop_loss_price}")
            return [parent_id, stop_id]
            
        try:
            contract = Stock(ticker, 'SMART', 'USD')
            self.ib.qualifyContracts(contract)
            
            # Allocate parent order ID
            parent_id = self.ib.client.getReqId()
            
            # 1. Parent Limit Order
            parent = LimitOrder(action, shares, limit_price)
            parent.orderId = parent_id
            parent.transmit = False
            
            # 2. Standing Stop Loss
            stop_action = 'SELL' if action == 'BUY' else 'BUY'
            stop = StopOrder(stop_action, shares, stop_loss_price)
            stop.parentId = parent_id
            stop.transmit = True
            
            # Place orders
            self.ib.placeOrder(contract, parent)
            self.ib.placeOrder(contract, stop)
            
            print(f"Submitted Bracket Order for {ticker}: {action} {shares} @ {limit_price}. Standing SL @ {stop_loss_price}")
            return [parent_id, parent_id + 1]
        except Exception as e:
            print(f"Error placing bracket order for {ticker}: {e}")
            return []

    def flatten_positions_and_kill(self, risk_controls) -> bool:
        """EMERGENCY KILL SWITCH:
        1. Cancel all open orders at the broker.
        2. Query all open positions.
        3. Place market orders to close (flatten) all positions.
        4. Trigger risk control lock file.
        """
        print("\n=== TRADING SYSTEM EMERGENCY KILL SWITCH ACTIVATED ===")
        
        # First check/trigger risk controls lock to prevent any concurrent entry
        risk_controls.trigger_kill_switch("Emergency kill switch activated.")
        
        if self.dry_run:
            print("[DRY RUN] Cancelling all mock open orders.")
            self.mock_orders = [o for o in self.mock_orders if o['status'] == 'Filled']
            
            print("[DRY RUN] Flattening all mock positions.")
            flattened_count = 0
            for ticker, pos in list(self.mock_positions.items()):
                shares = pos['shares']
                if shares != 0:
                    action = 'SELL' if shares > 0 else 'BUY'
                    print(f"[DRY RUN] Market order to flatten {ticker}: {action} {abs(shares)} shares")
                    flattened_count += 1
            self.mock_positions.clear()
            print(f"[DRY RUN] Emergency Kill complete. Flattened {flattened_count} positions.")
            return True
            
        try:
            # 1. Cancel all open orders
            print("Cancelling all active open orders at broker...")
            for trade in self.ib.openTrades():
                self.ib.cancelOrder(trade.order)
            
            # Wait briefly to let cancellations process
            time.sleep(1)
            
            # 2. Get positions
            positions = self.ib.positions()
            flattened_count = 0
            
            # 3. Submit market orders to flatten
            for pos in positions:
                ticker = pos.contract.symbol
                shares = pos.position
                
                if shares != 0:
                    close_action = 'SELL' if shares > 0 else 'BUY'
                    close_qty = abs(shares)
                    
                    contract = Stock(ticker, 'SMART', 'USD')
                    self.ib.qualifyContracts(contract)
                    
                    market_order = MarketOrder(close_action, close_qty)
                    self.ib.placeOrder(contract, market_order)
                    print(f"Flattening position {ticker}: {close_action} {close_qty} shares via Market Order")
                    flattened_count += 1
                    
            print(f"Emergency Kill complete. Submitted market orders to flatten {flattened_count} positions.")
            return True
        except Exception as e:
            print(f"CRITICAL ERROR executing emergency kill switch: {e}")
            return False
