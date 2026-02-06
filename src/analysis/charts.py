"""Interactive Plotly chart functions for trade visualization."""

from __future__ import annotations

from pathlib import Path

import plotly.graph_objects as go

from src.core.engine import EquityPoint
from src.core.types import Candle, Trade


def plot_equity_curve(
    equity_curve: list[EquityPoint],
    output_path: str | Path,
    title: str = "Equity Curve",
) -> None:
    """Plot an equity curve with drawdown shading and save as HTML.

    Args:
        equity_curve: List of EquityPoint (timestamp, equity).
        output_path: File path for the HTML output.
        title: Chart title.
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    fig = go.Figure()

    if not equity_curve:
        fig.add_annotation(
            text="No data",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(size=20),
        )
        fig.update_layout(title=title)
        fig.write_html(str(output_path))
        return

    timestamps = [pt.timestamp for pt in equity_curve]
    equities = [pt.equity for pt in equity_curve]

    # Calculate running peak for drawdown shading
    peaks: list[float] = []
    peak = equities[0]
    for eq in equities:
        if eq > peak:
            peak = eq
        peaks.append(peak)

    # Peak line (upper bound for drawdown fill)
    fig.add_trace(
        go.Scatter(
            x=timestamps,
            y=peaks,
            mode="lines",
            line=dict(width=0),
            showlegend=False,
            hoverinfo="skip",
        )
    )

    # Equity line (fills down to equity from peak to show drawdown)
    fig.add_trace(
        go.Scatter(
            x=timestamps,
            y=equities,
            mode="lines",
            name="Equity",
            line=dict(color="rgb(31, 119, 180)", width=2),
            fill="tonexty",
            fillcolor="rgba(255, 0, 0, 0.15)",
        )
    )

    fig.update_layout(
        title=title,
        xaxis_title="Time",
        yaxis_title="Equity",
        template="plotly_white",
        hovermode="x unified",
    )

    fig.write_html(str(output_path))


def plot_trades(
    candles: list[Candle],
    trades: list[Trade],
    output_path: str | Path,
    title: str = "Price Chart with Trades",
) -> None:
    """Plot a candlestick chart with trade entry/exit markers and save as HTML.

    Args:
        candles: OHLCV candle data.
        trades: Completed trades to overlay on the chart.
        output_path: File path for the HTML output.
        title: Chart title.
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    fig = go.Figure()

    if not candles:
        fig.add_annotation(
            text="No data",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(size=20),
        )
        fig.update_layout(title=title)
        fig.write_html(str(output_path))
        return

    # Candlestick chart
    fig.add_trace(
        go.Candlestick(
            x=[c.timestamp for c in candles],
            open=[c.open for c in candles],
            high=[c.high for c in candles],
            low=[c.low for c in candles],
            close=[c.close for c in candles],
            name="Price",
        )
    )

    if trades:
        # Entry markers
        entry_x = [t.entry_time for t in trades]
        entry_y = [t.entry_price for t in trades]
        entry_colors = ["green" if t.side == "long" else "red" for t in trades]
        entry_text = [
            f"{'Long' if t.side == 'long' else 'Short'} Entry<br>"
            f"Price: {t.entry_price:.2f}<br>"
            f"Time: {t.entry_time}"
            for t in trades
        ]

        fig.add_trace(
            go.Scatter(
                x=entry_x,
                y=entry_y,
                mode="markers",
                name="Entry",
                marker=dict(
                    symbol="circle",
                    size=10,
                    color=entry_colors,
                    line=dict(width=1, color="black"),
                ),
                text=entry_text,
                hoverinfo="text",
            )
        )

        # Exit markers — symbol/color depends on exit_reason
        exit_x = [t.exit_time for t in trades]
        exit_y = [t.exit_price for t in trades]

        exit_symbols: list[str] = []
        exit_colors: list[str] = []
        exit_text: list[str] = []

        for t in trades:
            reason = t.exit_reason
            if reason == "take_profit":
                exit_symbols.append("triangle-up")
                exit_colors.append("green" if t.side == "long" else "red")
            elif reason == "stop_loss":
                exit_symbols.append("x")
                exit_colors.append("red")
            else:  # "signal"
                exit_symbols.append("square")
                exit_colors.append("blue")

            exit_text.append(
                f"{'Long' if t.side == 'long' else 'Short'} Exit ({reason})<br>"
                f"Price: {t.exit_price:.2f}<br>"
                f"Time: {t.exit_time}<br>"
                f"PnL: {t.pnl:+.2f}"
            )

        fig.add_trace(
            go.Scatter(
                x=exit_x,
                y=exit_y,
                mode="markers",
                name="Exit",
                marker=dict(
                    symbol=exit_symbols,
                    size=10,
                    color=exit_colors,
                    line=dict(width=1, color="black"),
                ),
                text=exit_text,
                hoverinfo="text",
            )
        )

    fig.update_layout(
        title=title,
        xaxis_title="Time",
        yaxis_title="Price",
        template="plotly_white",
        xaxis_rangeslider_visible=False,
    )

    fig.write_html(str(output_path))
