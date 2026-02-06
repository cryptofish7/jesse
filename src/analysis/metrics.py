"""Standalone metric calculation functions for trade analysis."""

from __future__ import annotations

import math

from src.core.engine import EquityPoint
from src.core.types import Trade


def calculate_win_rate(trades: list[Trade]) -> float:
    """Fraction of winning trades (0.0 to 1.0).

    Break-even trades (pnl == 0) count in the denominator but not as wins.
    Returns 0.0 if the trade list is empty.
    """
    if not trades:
        return 0.0
    winners = sum(1 for t in trades if t.pnl > 0)
    return winners / len(trades)


def calculate_profit_factor(trades: list[Trade]) -> float:
    """Gross profit divided by gross loss.

    Returns:
        0.0 if no trades or no winning trades.
        inf if there are winners but no losers.
        The ratio otherwise.
    """
    if not trades:
        return 0.0
    gross_profit = sum(t.pnl for t in trades if t.pnl > 0)
    gross_loss = abs(sum(t.pnl for t in trades if t.pnl < 0))
    if gross_loss == 0.0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def calculate_total_return(initial_balance: float, final_equity: float) -> float:
    """Total return as a decimal (e.g. 0.15 = 15%).

    Returns 0.0 if initial_balance is zero.
    """
    if initial_balance == 0:
        return 0.0
    return (final_equity - initial_balance) / initial_balance


def calculate_max_drawdown(equity_curve: list[EquityPoint]) -> float:
    """Maximum peak-to-trough drawdown as a decimal (e.g. 0.10 = 10%).

    Returns 0.0 for empty or single-point curves, or monotonically increasing curves.
    """
    if len(equity_curve) <= 1:
        return 0.0
    peak = equity_curve[0].equity
    max_dd = 0.0
    for point in equity_curve:
        if point.equity > peak:
            peak = point.equity
        if peak > 0:
            dd = (peak - point.equity) / peak
            max_dd = max(max_dd, dd)
    return max_dd


def calculate_sharpe_ratio(equity_curve: list[EquityPoint], risk_free_rate: float = 0.0) -> float:
    """Annualized Sharpe ratio from an equity curve.

    Calculates period-over-period returns, then annualizes assuming 252
    trading days per year.

    Returns 0.0 for curves with fewer than 2 points or zero standard deviation.
    """
    if len(equity_curve) < 2:
        return 0.0

    # Calculate period returns
    returns: list[float] = []
    for i in range(1, len(equity_curve)):
        prev_eq = equity_curve[i - 1].equity
        if prev_eq == 0:
            returns.append(0.0)
        else:
            returns.append((equity_curve[i].equity - prev_eq) / prev_eq)

    if not returns:
        return 0.0

    n = len(returns)
    mean_return = sum(returns) / n

    # Standard deviation (population)
    variance = sum((r - mean_return) ** 2 for r in returns) / n
    std_dev = math.sqrt(variance)

    if std_dev == 0.0:
        return 0.0

    # Annualize: multiply by sqrt(252)
    sharpe = (mean_return - risk_free_rate) * math.sqrt(252) / std_dev
    return sharpe
