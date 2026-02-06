"""Analysis module — metrics and visualization for trading results."""

from src.analysis.charts import plot_equity_curve, plot_trades
from src.analysis.metrics import (
    calculate_max_drawdown,
    calculate_profit_factor,
    calculate_sharpe_ratio,
    calculate_total_return,
    calculate_win_rate,
)

__all__ = [
    "calculate_max_drawdown",
    "calculate_profit_factor",
    "calculate_sharpe_ratio",
    "calculate_total_return",
    "calculate_win_rate",
    "plot_equity_curve",
    "plot_trades",
]
