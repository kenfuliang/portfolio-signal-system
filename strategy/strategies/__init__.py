"""The strategy zoo — 20 algorithms across the major systematic families."""
from .trend import TrendMA, GoldenCross, Momentum12_1, RocMomentum, Macd, AdxTrend
from .breakout import Breakout52w, Donchian, VolatilityBreakout, KeltnerBreakout
from .reversion import RsiReversion, BollingerReversion, MaEnvelopeDip, ZscoreReversion
from .allocation import (
    DualMomentum, SectorRotation, LowVolatility, RiskParity,
    RelativeStrength, VolAdjustedMomentum, MomentumRunner,
    ChampionTrendHaven, RiskManagedGrowth, AsymmetricTrend, TrendFilteredHold, EqualWeightHold,
)
from .vol_target import VolTargetMomentum

STRATEGY_CLASSES = [
    TrendMA, GoldenCross, Momentum12_1, RocMomentum, Macd, AdxTrend,
    Breakout52w, Donchian, VolatilityBreakout, KeltnerBreakout,
    RsiReversion, BollingerReversion, MaEnvelopeDip, ZscoreReversion,
    DualMomentum, SectorRotation, LowVolatility, RiskParity,
    RelativeStrength, VolAdjustedMomentum, MomentumRunner,
    ChampionTrendHaven, RiskManagedGrowth, AsymmetricTrend, TrendFilteredHold, EqualWeightHold,
    VolTargetMomentum,
]
