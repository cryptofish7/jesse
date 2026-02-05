"""Tests for core data types."""

from datetime import datetime

from src.core.types import Candle, MultiTimeframeData, Signal, TimeframeData, Trade


class TestCandle:
    def _make(self, **overrides) -> Candle:
        defaults = dict(
            timestamp=datetime(2024, 1, 1),
            open=100.0,
            high=110.0,
            low=90.0,
            close=105.0,
            volume=1000.0,
        )
        defaults.update(overrides)
        return Candle(**defaults)

    def test_is_bullish(self):
        c = self._make(open=100.0, close=105.0)
        assert c.is_bullish is True
        assert c.is_bearish is False

    def test_is_bearish(self):
        c = self._make(open=105.0, close=100.0)
        assert c.is_bearish is True
        assert c.is_bullish is False

    def test_doji_neither(self):
        c = self._make(open=100.0, close=100.0)
        assert c.is_bullish is False
        assert c.is_bearish is False

    def test_range(self):
        c = self._make(high=110.0, low=90.0)
        assert c.range == 20.0

    def test_body(self):
        c = self._make(open=100.0, close=105.0)
        assert c.body == 5.0
        c2 = self._make(open=105.0, close=100.0)
        assert c2.body == 5.0

    def test_default_oi_cvd(self):
        c = self._make()
        assert c.open_interest == 0.0
        assert c.cvd == 0.0

    def test_custom_oi_cvd(self):
        c = self._make(open_interest=500.0, cvd=42.0)
        assert c.open_interest == 500.0
        assert c.cvd == 42.0


class TestSignal:
    def test_open_long(self):
        s = Signal.open_long(size_percent=1.0, stop_loss=95000, take_profit=105000)
        assert s.direction == "long"
        assert s.size_percent == 1.0
        assert s.stop_loss == 95000
        assert s.take_profit == 105000
        assert s.position_id is None

    def test_open_short(self):
        s = Signal.open_short(size_percent=0.5, stop_loss=105000, take_profit=95000)
        assert s.direction == "short"
        assert s.size_percent == 0.5
        assert s.stop_loss == 105000
        assert s.take_profit == 95000

    def test_close_all(self):
        s = Signal.close()
        assert s.direction == "close"
        assert s.position_id is None

    def test_close_specific(self):
        s = Signal.close(position_id="abc123")
        assert s.direction == "close"
        assert s.position_id == "abc123"


class TestPosition:
    def test_unrealized_pnl_long_profit(self):
        from src.core.types import Position

        p = Position(
            id="p1",
            side="long",
            entry_price=100.0,
            entry_time=datetime(2024, 1, 1),
            size=1.0,
            size_usd=100.0,
            stop_loss=90.0,
            take_profit=120.0,
        )
        assert p.unrealized_pnl(110.0) == 10.0

    def test_unrealized_pnl_long_loss(self):
        from src.core.types import Position

        p = Position(
            id="p1",
            side="long",
            entry_price=100.0,
            entry_time=datetime(2024, 1, 1),
            size=1.0,
            size_usd=100.0,
            stop_loss=90.0,
            take_profit=120.0,
        )
        assert p.unrealized_pnl(90.0) == -10.0

    def test_unrealized_pnl_short_profit(self):
        from src.core.types import Position

        p = Position(
            id="p1",
            side="short",
            entry_price=100.0,
            entry_time=datetime(2024, 1, 1),
            size=1.0,
            size_usd=100.0,
            stop_loss=110.0,
            take_profit=80.0,
        )
        assert p.unrealized_pnl(90.0) == 10.0

    def test_unrealized_pnl_short_loss(self):
        from src.core.types import Position

        p = Position(
            id="p1",
            side="short",
            entry_price=100.0,
            entry_time=datetime(2024, 1, 1),
            size=1.0,
            size_usd=100.0,
            stop_loss=110.0,
            take_profit=80.0,
        )
        assert p.unrealized_pnl(110.0) == -10.0

    def test_generate_id_unique(self):
        from src.core.types import Position

        ids = {Position.generate_id() for _ in range(100)}
        assert len(ids) == 100


class TestTrade:
    def test_trade_fields(self):
        t = Trade(
            id="t1",
            side="long",
            entry_price=100.0,
            exit_price=110.0,
            entry_time=datetime(2024, 1, 1),
            exit_time=datetime(2024, 1, 2),
            size=1.0,
            size_usd=100.0,
            pnl=10.0,
            pnl_percent=10.0,
            exit_reason="take_profit",
        )
        assert t.pnl == 10.0
        assert t.exit_reason == "take_profit"


class TestTimeframeData:
    def test_defaults(self):
        c = Candle(
            timestamp=datetime(2024, 1, 1),
            open=100.0,
            high=110.0,
            low=90.0,
            close=105.0,
            volume=1000.0,
        )
        td = TimeframeData(latest=c)
        assert td.latest is c
        assert td.history == []

    def test_multi_timeframe_data(self):
        c = Candle(
            timestamp=datetime(2024, 1, 1),
            open=100.0,
            high=110.0,
            low=90.0,
            close=105.0,
            volume=1000.0,
        )
        mtf = MultiTimeframeData()
        mtf["1m"] = TimeframeData(latest=c)
        mtf["4h"] = TimeframeData(latest=c, history=[c, c])
        assert mtf["1m"].latest.close == 105.0
        assert len(mtf["4h"].history) == 2
