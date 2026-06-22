import pandas as pd
import numpy as np
from datetime import datetime
from features.library import compute_features
from models.direction_model.model import DirectionModel
from models.volatility_model.model import VolatilityModel
from models.factor_filter.filter import FactorFilter
from strategy_signals.generator import SignalGenerator
from risk.sizing import PositionSizer
from backtest.cost_model import TransactionCostModel

class WalkForwardBacktester:
    """Runs a walk-forward out-of-sample simulation using the actual model ensemble,
    signal generator, position sizer, and stop-loss logic.
    """
    
    def __init__(self, 
                 train_window_bars: int = 252, 
                 test_window_bars: int = 63,
                 initial_capital: float = 100000.0,
                 risk_fraction: float = 0.01,
                 confidence_threshold: float = 0.55):
        self.train_window_bars = train_window_bars
        self.test_window_bars = test_window_bars
        self.initial_capital = initial_capital
        
        self.direction_model = DirectionModel(forward_window=5)
        self.volatility_model = VolatilityModel(fallback_window=20)
        self.factor_filter = FactorFilter(p_value_threshold=0.05)
        self.signal_gen = SignalGenerator(confidence_threshold=confidence_threshold)
        self.sizer = PositionSizer(risk_fraction=risk_fraction, stop_atr_mult=2.0)
        self.cost_model = TransactionCostModel()
        
    def run_backtest(self, ticker: str, df: pd.DataFrame, index_df: pd.DataFrame) -> pd.DataFrame:
        """Run the rolling walk-forward backtest."""
        if df.empty or len(df) < self.train_window_bars + self.test_window_bars:
            print(f"Insufficient history to backtest {ticker}")
            return pd.DataFrame()
            
        # 1. Compute features on the entire dataset to ensure consistency
        df_feats = compute_features(df, index_df)
        
        # Track simulated portfolio state
        equity = self.initial_capital
        portfolio_history = []
        
        # Position state: None or dict: {'type': 'BUY'/'SELL', 'entry_price': float, 'shares': int, 'stop_loss': float, 'bars_held': int}
        position = None
        
        total_bars = len(df_feats)
        start_idx = self.train_window_bars
        
        # Make a rolling window progression
        for i in range(start_idx, total_bars):
            # The current timestamp
            current_bar = df_feats.iloc[i]
            current_time = current_bar['timestamp']
            
            # Retrain model periodically (every test_window_bars)
            if (i - start_idx) % self.test_window_bars == 0:
                train_data = df_feats.iloc[i - self.train_window_bars : i]
                self.direction_model.fit(train_data)
                
                # Fit Volatility Model
                if 'ret_1d' in train_data.columns:
                    self.volatility_model.fit(train_data['ret_1d'])
            
            # Sub-slice data up to current timestamp for signal generation to avoid look-ahead
            data_up_to_now = df_feats.iloc[:i+1]
            
            # Predict direction probability for latest bar
            probs = self.direction_model.predict_probability(data_up_to_now)
            latest_prob = probs.iloc[-1]
            
            # Forecast volatility for sizing
            ticker_returns = data_up_to_now['ret_1d']
            ann_vol_forecast = self.volatility_model.forecast_volatility(ticker_returns)
            atr_val = data_up_to_now['atr_14'].iloc[-1]
            
            # Run Fama-French filter
            # To simulate we pass the ticker returns and index returns from the training window
            train_returns = data_up_to_now['ret_1d'].tail(60)
            if index_df is not None and not index_df.empty:
                # Align index returns
                idx_returns = data_up_to_now['index_ret_1d'].tail(60) if 'index_ret_1d' in data_up_to_now.columns else pd.Series(0.0, index=train_returns.index)
            else:
                idx_returns = pd.Series(0.0, index=train_returns.index)
                
            filter_results = self.factor_filter.analyze_exposure(train_returns, idx_returns)
            
            # Generate signals
            # Note: We simulate empty blackout calendar here
            signal = self.signal_gen.generate_signals(
                ticker=ticker,
                df=data_up_to_now,
                direction_probs=probs,
                factor_filter_results=filter_results,
                current_time=current_time,
                blackout_df=None
            )
            
            # Simulate Position management
            # Daily prices
            open_price = current_bar['open']
            high_price = current_bar['high']
            low_price = current_bar['low']
            close_price = current_bar['close']
            volume = current_bar['volume']
            
            # Update equity history
            pnl = 0.0
            
            if position:
                # We have an open position. Check if stop loss was hit!
                hit_stop = False
                exit_price = close_price
                
                if position['type'] == 'BUY':
                    # Stop loss triggered if low goes below stop price
                    if low_price <= position['stop_loss']:
                        hit_stop = True
                        # Assume execution at the stop loss price (or worse, with slippage)
                        exit_price = position['stop_loss']
                elif position['type'] == 'SELL':
                    # Stop loss triggered if high goes above stop price
                    if high_price <= position['stop_loss']: # Wait, for sell, if high goes above stop price
                        hit_stop = True
                        exit_price = position['stop_loss']
                
                # Update holding counter
                position['bars_held'] += 1
                
                # Check exit conditions: stop hit or maximum holding period (5 bars)
                if hit_stop or position['bars_held'] >= 5:
                    # Execute Close
                    shares = position['shares']
                    # Calculate transaction costs
                    costs = self.cost_model.calculate_total_costs(shares, exit_price, avg_daily_volume=volume)
                    
                    if position['type'] == 'BUY':
                        trade_pnl = (exit_price - position['entry_price']) * shares - costs
                    else:
                        trade_pnl = (position['entry_price'] - exit_price) * shares - costs
                        
                    equity += trade_pnl
                    position = None
                    # print(f"[{current_time.date()}] EXITED position in {ticker} @ {exit_price:.2f}. Trade PnL: {trade_pnl:.2f}. Reason: {'Stop Loss' if hit_stop else 'Hold Limit'}")
                else:
                    # Mark-to-market PnL for logging
                    if position['type'] == 'BUY':
                        pnl = (close_price - position['entry_price']) * position['shares']
                    else:
                        pnl = (position['entry_price'] - close_price) * position['shares']
            else:
                # No position. Check for entry signal
                if signal['action'] in ['BUY', 'SELL']:
                    # Size the position
                    sizing_res = self.sizer.calculate_position_size(equity, open_price, atr_val, signal['action'])
                    shares = sizing_res['shares']
                    stop_loss_price = sizing_res['stop_loss_price']
                    
                    if shares > 0:
                        # Pay entry costs
                        costs = self.cost_model.calculate_total_costs(shares, open_price, avg_daily_volume=volume)
                        equity -= costs
                        
                        position = {
                            'type': signal['action'],
                            'entry_price': open_price,
                            'shares': shares,
                            'stop_loss': stop_loss_price,
                            'bars_held': 0
                        }
                        # print(f"[{current_time.date()}] ENTERED {signal['action']} on {ticker}: {shares} shares @ {open_price:.2f}. Stop Loss: {stop_loss_price:.2f}")
            
            portfolio_history.append({
                'timestamp': current_time,
                'close': close_price,
                'equity': equity + pnl,
                'position_active': 1 if position else 0,
                'signal_prob': latest_prob,
                'atr': atr_val
            })
            
        return pd.DataFrame(portfolio_history)
