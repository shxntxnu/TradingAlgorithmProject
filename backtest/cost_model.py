class TransactionCostModel:
    """Simulates real execution costs including commissions, bid-ask spreads,
    and market impact (slippage) as a function of daily volume.
    """
    
    def __init__(self, 
                 commission_per_share: float = 0.005, 
                 min_commission: float = 1.0, 
                 half_spread_pct: float = 0.0005, 
                 market_impact_coef: float = 0.1):
        self.commission_per_share = commission_per_share
        self.min_commission = min_commission
        self.half_spread_pct = half_spread_pct
        self.market_impact_coef = market_impact_coef

    def calculate_total_costs(self, 
                              shares: float, 
                              price: float, 
                              avg_daily_volume: float = None) -> float:
        """Estimate the sum of commission, spread crossing, and market impact slippage."""
        if shares <= 0:
            return 0.0
            
        # 1. Commission cost
        commission = max(shares * self.commission_per_share, self.min_commission)
        
        # 2. Spread crossing cost (half of bid-ask spread)
        spread_cost = shares * price * self.half_spread_pct
        
        # 3. Market impact slippage
        # Formula: impact_coef * (shares / ADV) * order_value
        slippage_cost = 0.0
        if avg_daily_volume and avg_daily_volume > 0:
            size_fraction = shares / avg_daily_volume
            slippage_cost = self.market_impact_coef * size_fraction * (shares * price)
            
        return commission + spread_cost + slippage_cost
