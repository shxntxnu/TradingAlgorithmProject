# User Manual: Multi-Asset Algorithmic Trading System

This guide outlines the features, configuration rules, and critical warnings for the multi-asset extension located in the `multi_asset_system/` directory.

---

## 📂 System Directory Layout

```
multi_asset_system/
├── data_ingester.py          # Data ingestion directly from TWS/Gateway
├── risk_controls.py          # Asset class limits & multiplier-aware sizer
├── run_multi_asset_trader.py # Master loop (25 ticker limit, 1s pacing delays)
└── multi_asset_guide.md      # This user manual and warning documentation
```

---

## 📈 Symbol / Ticker Formatting Rules

The data ingester parses symbols into qualified IBKR contracts using specific text boundaries:

1. **Stocks & ETFs** (e.g., `AAPL`, `MSFT`, `SPY`)
   - Format: Standard ticker symbol string.
   - Routing: Uses the `SMART` routing exchange and denominated in `USD`.
2. **Forex Currency Pairs** (e.g., `EURUSD` or `GBP-USD`)
   - Format: Direct 6-character pair or `Symbol1-Symbol2` split.
   - Routing: Cash/Forex execution. denominate price in midpoint ticks.
3. **Futures Contracts** (e.g., `ES-202609-GLOBEX`)
   - Format: `[Underlying Symbol]-[Contract Month (YYYYMM)]-[Exchange]`
   - Examples:
     - `ES-202609-GLOBEX` (E-mini S&P 500 futures, Sep 2026 expiry, traded on GLOBEX/CME)
     - `CL-202611-NYMEX` (Crude Oil futures, Nov 2026 expiry, traded on NYMEX)
     - `GC-202612-NYMEX` (Gold futures, Dec 2026 expiry, traded on NYMEX)

---

## 🚦 System Limits & Protective Safeguards

To prevent overwhelming TWS/Gateway and protect account capital, the following limits are hard-coded into the execution cycle:

| Limit / Rule | Default Value | Purpose |
| :--- | :--- | :--- |
| **API Pacing Delay** | `1.0` second | Sleeps 1 second before evaluating any contract to respect IBKR rate limits. |
| **Analysis Ticker Cap** | `25` tickers | Slices input ticker lists to a maximum of 25 items to prevent request timeouts. |
| **Max Equities Positions** | `4` open positions | Caps equity exposure count. |
| **Max Forex Positions** | `3` open positions | Caps currency exposure count. |
| **Max Futures Positions** | `3` open positions | Caps commodity/index futures exposure count. |
| **Total Position Limit** | `8` open positions | Absolute cap on concurrent open positions in the portfolio. |
| **Equity Risk Fraction** | `1.0%` of NLV | Risk allocation per equity trade. |
| **FX/Futures Risk Fraction** | `0.5%` of NLV | Reduced risk fraction to account for leverage volatility. |

---

## 🧮 Multiplier-Aware Position Sizing

For leveraged contracts, price movements are scaled by a **Contract Multiplier**. The `MultiAssetSizer` resolves these multipliers dynamically to prevent sizing errors:
- **E-mini S&P 500 (ES)**: Multiplier is **`50.0`** (Each index point is worth $50).
- **E-mini Nasdaq 100 (NQ)**: Multiplier is **`20.0`** (Each index point is worth $20).
- **Crude Oil (CL)**: Multiplier is **`1000.0`** (Each dollar price move is worth $1,000).
- **Gold Futures (GC)**: Multiplier is **`100.0`** (Each dollar price move is worth $100).
- **Stocks & Forex**: Multiplier is **`1.0`**.

### Contract Sizing Formula:
$$\text{Contracts/Shares} = \text{Floor}\left(\frac{\text{Account Equity} \times \text{Risk Fraction}}{\text{Stop Distance} \times \text{Contract Multiplier}}\right)$$

*Example (ES Future)*:
- Account Equity: \$1,000,000
- Risk Fraction: 0.5% = \$5,000 risk amount
- Entry Price: 5,400.00 | Volatility ATR: 50.00 | Stop Distance (2x ATR): 100.00 points
- Multiplier: 50
- $$\text{Contracts} = \text{Floor}\left(\frac{5,000}{100 \times 50}\right) = \text{Floor}\left(\frac{5,000}{5,000}\right) = 1 \text{ contract}$$

---

## ⚠️ Critical Warnings

Before running live or paper trading with this extension, adhere to these warnings:

### 1. Market Data Subscriptions (IBKR Permissions)
> [!WARNING]
> Retrieving data directly through `ib.reqHistoricalData` requires **active market data subscriptions** on your IBKR account for the asset classes you wish to query (specifically OPRA for US Options, CME/CBOT/NYMEX for Futures, and US Equity real-time feeds).
> If you do not have active subscriptions, TWS will return a "No Market Data Permissions" error and the historical data load will return empty.
>
> *Note: Forex midpoint data is typically available without paid subscriptions.*

### 2. Futures Contract Rollovers
> [!CAUTION]
> Futures contracts expire. The system **does not automatically roll contracts**. You must manually update your ticker symbol inputs (e.g. changing `ES-202609-GLOBEX` to `ES-202612-GLOBEX`) in your scheduler configurations prior to expiry week to prevent execution locks.

### 3. Margin & Leverage Risk
> [!CAUTION]
> Futures and Forex are highly leveraged instruments. While the position sizer caps risk per trade at `0.5%` of equity, the **nominal exposure** of a futures contract can be massive (e.g., 1 contract of ES at 5,400 represents $270,000 in nominal value). Ensure your account has sufficient margin to cover overnight margins, and never reactively adjust your risk fractions.
