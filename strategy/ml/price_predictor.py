"""ML-based price direction prediction strategy.

Uses gradient boosting (XGBoost/LightGBM) to predict future price direction
and generate trading signals. Features are extracted via FeatureEngineer.

Strategy logic:
1. Extract features from OHLCV data on each bar
2. Use trained ML model to predict direction (UP/DOWN/FLAT)
3. Generate signals based on:
   - Predicted direction with sufficient confidence
   - Confirmation from technical indicators (regime, volume)
   - Position state (avoid redundant entries)

Modes:
- Live: Uses pre-trained model loaded from disk
- Backtest: Can train inline or use pre-trained model

Usage:
    from strategy.ml import PricePredictorStrategy

    # With pre-trained model
    strategy = PricePredictorStrategy(
        name="ml_predictor",
        params={"model_path": "models/ml_BTC_USDT_20260101"},
    )

    # Or train inline during backtest
    strategy = PricePredictorStrategy(
        name="ml_predictor",
        params={"auto_train": True, "pair": "BTC/USDT", "timeframe": "1h"},
    )
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional

import structlog

from strategy.base import Signal, SignalType, StrategyBase, StrategyContext
from strategy.ml.feature_engineer import FeatureConfig, FeatureEngineer
from strategy.ml.model_manager import ModelManager
from strategy.regime import MarketRegime, RegimeDetector
from strategy.cta import calculate_atr_f

logger = structlog.get_logger(__name__)


@dataclass
class MLPredictorConfig:
    """Configuration for ML price prediction strategy.

    Attributes:
        # Model settings
        model_path: Path to pre-trained model (if None, auto_train must be True)
        auto_train: Whether to train model on-the-fly during backtest
        model_type: "xgboost" or "lightgbm"
        horizon: Forward-looking periods for prediction
        threshold: Return threshold for UP/DOWN labels

        # Signal generation
        confidence_threshold: Minimum confidence to act on prediction
        use_regime_filter: Whether to filter signals with regime detection
        use_volume_filter: Whether to require volume confirmation
        volume_ratio_threshold: Minimum volume ratio for entry

        # Risk management
        use_atr_exit: Whether to use ATR-based stop loss / take profit
        atr_period: ATR calculation period
        atr_stop_multiplier: Stop loss in ATR multiples
        atr_take_multiplier: Take profit in ATR multiples

        # Feature config
        feature_config: FeatureConfig for feature engineering
    """
    model_path: Optional[str] = None
    auto_train: bool = False
    model_type: str = "xgboost"
    horizon: int = 5
    threshold: float = 0.001
    confidence_threshold: Decimal = Decimal("0.45")
    use_regime_filter: bool = True
    use_volume_filter: bool = True
    volume_ratio_threshold: float = 1.2

    # ATR exit
    use_atr_exit: bool = True
    atr_period: int = 14
    atr_stop_multiplier: Decimal = Decimal("2")
    atr_take_multiplier: Decimal = Decimal("3")

    # Feature config
    feature_config: FeatureConfig = field(default_factory=FeatureConfig)


class PricePredictorStrategy(StrategyBase):
    """ML-based price direction prediction strategy.

    Uses a trained gradient boosting model to predict future price direction
    (UP, DOWN, or FLAT) from technical indicator features, then generates
    LONG/SHORT signals when the prediction has sufficient confidence.

    Key features:
    - Multi-class prediction (UP/DOWN/FLAT) with probability output
    - Confidence threshold to filter weak predictions
    - Regime filter to avoid trading in choppy markets
    - Volume filter for entry confirmation
    - ATR-based stop loss and take profit
    - Walk-forward validation support
    """

    def __init__(
        self,
        name: str = "ml_predictor",
        params: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(name, params)

        self.config = MLPredictorConfig(
            model_path=self.get_param("model_path", None),
            auto_train=self.get_param("auto_train", False),
            model_type=self.get_param("model_type", "xgboost"),
            horizon=self.get_param("horizon", 5),
            threshold=self.get_param("threshold", 0.001),
            confidence_threshold=Decimal(str(self.get_param("confidence_threshold", "0.45"))),
            use_regime_filter=self.get_param("use_regime_filter", True),
            use_volume_filter=self.get_param("use_volume_filter", True),
            volume_ratio_threshold=self.get_param("volume_ratio_threshold", 1.2),
            use_atr_exit=self.get_param("use_atr_exit", True),
            atr_period=self.get_param("atr_period", 14),
            atr_stop_multiplier=Decimal(str(self.get_param("atr_stop_multiplier", "2"))),
            atr_take_multiplier=Decimal(str(self.get_param("atr_take_multiplier", "3"))),
            feature_config=FeatureConfig(
                ma_periods=self.get_param("ma_periods", [5, 10, 20, 50]),
                rsi_period=self.get_param("rsi_period", 14),
                atr_period=self.get_param("atr_period", 14),
                adx_period=self.get_param("adx_period", 14),
                return_lookbacks=self.get_param("return_lookbacks", [1, 3, 5, 10, 20]),
            ),
        )

        # Core components
        self.feature_engineer = FeatureEngineer(self.config.feature_config)
        self.model_manager = ModelManager(self.config.feature_config)

        # Regime detector
        self._regime_detector = RegimeDetector()
        self._current_regime: MarketRegime = MarketRegime.UNKNOWN

        # Trade state for ATR exit
        self._trade_direction: Optional[str] = None
        self._trade_entry_price: Optional[float] = None
        self._trade_stop_price: Optional[float] = None
        self._trade_take_price: Optional[float] = None

        # Prediction history for smoothing
        self._prediction_history: List[int] = []
        self._prediction_window: int = 3  # Majority vote window

        # Model loaded flag
        self._model_ready: bool = False

        self.logger = structlog.get_logger(__name__).bind(strategy=name)

    def initialize(self) -> None:
        """Initialize strategy - load or train model."""
        self.logger.info("initializing_ml_strategy")

        errors = self.validate_params()
        if errors:
            raise ValueError(f"Invalid parameters: {', '.join(errors)}")

        # Reset state
        self._reset_trade_state()
        self._prediction_history.clear()
        self._current_regime = MarketRegime.UNKNOWN

        # Load model or prepare for auto-training
        if self.config.model_path:
            try:
                self.model_manager.load_model(self.config.model_path)
                self._model_ready = True
                self.logger.info("model_loaded", path=self.config.model_path)
            except Exception as e:
                self.logger.error("model_load_failed", error=str(e))
                self._model_ready = False
        elif self.config.auto_train:
            self.logger.info("auto_train_mode", status="model_will_be_trained_at_first_signal")
            self._model_ready = False
        else:
            self.logger.warning("no_model_path_and_auto_train_disabled")

    def _try_auto_train(self, context: StrategyContext) -> bool:
        """Attempt to auto-train model from historical data.

        Called lazily on first signal generation when auto_train=True.

        Args:
            context: Current strategy context

        Returns:
            True if model is ready after training attempt
        """
        if self._model_ready:
            return True

        if not self.config.auto_train:
            return False

        try:
            self.logger.info("auto_training_start", pair=context.pair, timeframe=context.timeframe)

            data = self.model_manager.prepare_training_data(
                pair=context.pair,
                timeframe=context.timeframe,
                horizon=self.config.horizon,
                threshold=self.config.threshold,
            )

            if data is None:
                self.logger.error("auto_train_failed", reason="insufficient_data")
                return False

            self.model_manager.train(data, model_type=self.config.model_type)
            self._model_ready = True

            # Log feature importance
            importance = self.model_manager.get_feature_importance(top_n=10)
            for fname, fval in importance:
                self.logger.info("feature_importance", feature=fname, importance=fval)

            return True

        except Exception as e:
            self.logger.error("auto_train_error", error=str(e))
            return False

    def generate_signal(self, context: StrategyContext) -> Signal:
        """Generate trading signal from ML prediction.

        Pipeline:
        1. Check ATR stop loss / take profit (highest priority)
        2. Extract features from current market data
        3. Run ML model inference
        4. Apply filters (confidence, regime, volume)
        5. Smooth predictions (majority vote)
        6. Generate signal

        Args:
            context: Current market and account context

        Returns:
            Signal with LONG/SHORT/CLOSE/HOLD
        """
        # Auto-train if needed
        if not self._model_ready:
            if not self._try_auto_train(context):
                return self._hold_signal(context, reason="model_not_ready")

        # Fast path for backtest
        if context.has_fast_data:
            return self._generate_signal_fast(context)

        # Decimal path (live trading)
        candles = context.candles
        current_price = context.current_price
        current_price_f = float(current_price)

        if len(candles) < self.config.feature_config.min_candles:
            return self._hold_signal(context, reason="insufficient_data")

        # --- Priority 1: ATR stop loss / take profit ---
        atr_exit = self._check_atr_exit(current_price_f, context.current_time)
        if atr_exit is not None:
            return atr_exit

        # --- Priority 2: Feature extraction ---
        features = self.feature_engineer.extract(candles)
        if features is None:
            return self._hold_signal(context, reason="feature_extraction_failed")

        # --- Priority 3: ML prediction ---
        prediction, confidence, class_probs = self.model_manager.predict(features)

        # Smooth prediction (majority vote)
        self._prediction_history.append(prediction)
        if len(self._prediction_history) > self._prediction_window:
            self._prediction_history = self._prediction_history[-self._prediction_window:]
        smoothed = self._get_majority_prediction()

        # --- Priority 4: Signal generation ---
        signal_type = self._determine_signal(
            smoothed, confidence, features, context,
        )

        # Set ATR exit on new entry
        if signal_type in (SignalType.LONG, SignalType.SHORT):
            direction = "long" if signal_type == SignalType.LONG else "short"
            self._set_atr_exit_from_features(features, direction, current_price_f)

        metadata = {
            "strategy": "ml_predictor",
            "prediction": prediction,
            "smoothed_prediction": smoothed,
            "confidence": float(confidence),
            "prob_down": class_probs.get(-1, 0),
            "prob_flat": class_probs.get(0, 0),
            "prob_up": class_probs.get(1, 0),
            "regime": self._current_regime.value,
        }

        return Signal(
            signal_type=signal_type,
            pair=context.pair,
            timestamp=context.current_time,
            price=current_price,
            confidence=Decimal(str(round(confidence, 6))),
            metadata=metadata,
        )

    def _generate_signal_fast(self, context: StrategyContext) -> Signal:
        """Fast float-based signal generation for backtesting."""
        closes = context.closes_f  # type: ignore
        opens = context.opens_f  # type: ignore
        highs = context.highs_f  # type: ignore
        lows = context.lows_f  # type: ignore
        volumes = context.volumes_f  # type: ignore

        current_price = context.current_price
        current_price_f = float(current_price)
        current_time = context.current_time

        if len(closes) < self.config.feature_config.min_candles:
            return self._hold_signal(context, reason="insufficient_data")

        # ATR exit
        if self._trade_direction is not None and self._trade_stop_price is not None:
            if self._trade_direction == "long":
                if current_price_f <= self._trade_stop_price:
                    self._reset_trade_state()
                    return Signal(
                        signal_type=SignalType.CLOSE_LONG, pair="",
                        timestamp=current_time, price=current_price,
                        confidence=Decimal("1.0"),
                        metadata={"reason": "atr_stop_loss"},
                    )
                if self._trade_take_price and current_price_f >= self._trade_take_price:
                    self._reset_trade_state()
                    return Signal(
                        signal_type=SignalType.CLOSE_LONG, pair="",
                        timestamp=current_time, price=current_price,
                        confidence=Decimal("1.0"),
                        metadata={"reason": "atr_take_profit"},
                    )
            elif self._trade_direction == "short":
                if current_price_f >= self._trade_stop_price:
                    self._reset_trade_state()
                    return Signal(
                        signal_type=SignalType.CLOSE_SHORT, pair="",
                        timestamp=current_time, price=current_price,
                        confidence=Decimal("1.0"),
                        metadata={"reason": "atr_stop_loss"},
                    )
                if self._trade_take_price and current_price_f <= self._trade_take_price:
                    self._reset_trade_state()
                    return Signal(
                        signal_type=SignalType.CLOSE_SHORT, pair="",
                        timestamp=current_time, price=current_price,
                        confidence=Decimal("1.0"),
                        metadata={"reason": "atr_take_profit"},
                    )

        # Feature extraction
        features = self.feature_engineer.extract_f(
            opens, highs, lows, closes, volumes,
        )
        if features is None:
            return self._hold_signal(context, reason="feature_extraction_failed")

        # ML prediction
        prediction, confidence, class_probs = self.model_manager.predict(features)

        # Smooth prediction
        self._prediction_history.append(prediction)
        if len(self._prediction_history) > self._prediction_window:
            self._prediction_history = self._prediction_history[-self._prediction_window:]
        smoothed = self._get_majority_prediction()

        # Regime detection (float)
        if self.config.use_regime_filter:
            self._current_regime, _ = self._regime_detector.detect_with_scores_f(
                highs, lows, closes,
            )
        else:
            self._current_regime = MarketRegime.STRONG_TREND

        # Determine signal
        signal_type = self._determine_signal_fast(
            smoothed, confidence, features, context,
        )

        # ATR exit setup on new entry
        if signal_type in (SignalType.LONG, SignalType.SHORT):
            direction = "long" if signal_type == SignalType.LONG else "short"
            atr_f = calculate_atr_f(highs, lows, closes, self.config.atr_period)
            if atr_f is not None:
                stop_mult = float(self.config.atr_stop_multiplier)
                take_mult = float(self.config.atr_take_multiplier)
                if direction == "long":
                    self._trade_stop_price = current_price_f - atr_f * stop_mult
                    self._trade_take_price = current_price_f + atr_f * take_mult
                else:
                    self._trade_stop_price = current_price_f + atr_f * stop_mult
                    self._trade_take_price = current_price_f - atr_f * take_mult
                self._trade_direction = direction
                self._trade_entry_price = current_price_f

        metadata = {
            "strategy": "ml_predictor",
            "prediction": prediction,
            "smoothed_prediction": smoothed,
            "confidence": float(confidence),
            "prob_down": class_probs.get(-1, 0),
            "prob_flat": class_probs.get(0, 0),
            "prob_up": class_probs.get(1, 0),
            "regime": self._current_regime.value,
        }

        return Signal(
            signal_type=signal_type,
            pair=context.pair,
            timestamp=current_time,
            price=current_price,
            confidence=Decimal(str(round(confidence, 6))),
            metadata=metadata,
        )

    def _determine_signal(
        self,
        prediction: int,
        confidence: float,
        features: Dict[str, float],
        context: StrategyContext,
    ) -> SignalType:
        """Determine signal type from prediction and filters (Decimal path)."""
        # Confidence filter
        if confidence < float(self.config.confidence_threshold):
            return SignalType.HOLD

        # Regime filter
        if self.config.use_regime_filter:
            candles = context.candles
            self._current_regime, _ = self._regime_detector.detect_with_scores(candles)
            if prediction != 0 and self._current_regime in (
                MarketRegime.RANGING, MarketRegime.UNKNOWN,
            ):
                return SignalType.HOLD

        # Volume filter
        if self.config.use_volume_filter:
            vol_ratio = features.get("volume_ratio", 1.0)
            if prediction != 0 and vol_ratio < self.config.volume_ratio_threshold:
                return SignalType.HOLD

        # Position-aware signal generation
        position = context.get_position()
        current_side = None
        if position and not position.is_flat:
            current_side = "long" if position.is_long else "short"

        if prediction == 1:  # UP
            if current_side == "long":
                return SignalType.HOLD
            elif current_side == "short":
                return SignalType.CLOSE_SHORT
            else:
                return SignalType.LONG

        elif prediction == -1:  # DOWN
            if current_side == "short":
                return SignalType.HOLD
            elif current_side == "long":
                return SignalType.CLOSE_LONG
            else:
                return SignalType.SHORT

        # prediction == 0 (FLAT)
        if current_side == "long":
            return SignalType.CLOSE_LONG
        elif current_side == "short":
            return SignalType.CLOSE_SHORT

        return SignalType.HOLD

    def _determine_signal_fast(
        self,
        prediction: int,
        confidence: float,
        features: Dict[str, float],
        context: StrategyContext,  # noqa: ARG002 — reserved for future filters
    ) -> SignalType:
        """Determine signal type from prediction and filters (fast path).

        Note: position state is tracked by BacktraderStrategyAdapter,
        so we don't check position here — we just return entry/exit signals.
        """
        # Confidence filter
        if confidence < float(self.config.confidence_threshold):
            return SignalType.HOLD

        # Regime filter
        if self.config.use_regime_filter:
            if prediction != 0 and self._current_regime in (
                MarketRegime.RANGING, MarketRegime.UNKNOWN,
            ):
                return SignalType.HOLD

        # Volume filter
        if self.config.use_volume_filter:
            vol_ratio = features.get("volume_ratio", 1.0)
            if prediction != 0 and vol_ratio < self.config.volume_ratio_threshold:
                return SignalType.HOLD

        if prediction == 1:  # UP
            return SignalType.LONG
        elif prediction == -1:  # DOWN
            return SignalType.SHORT

        return SignalType.HOLD

    def _check_atr_exit(
        self, current_price_f: float, current_time: int,
    ) -> Optional[Signal]:
        """Check ATR stop loss / take profit (Decimal path)."""
        if self._trade_direction is None or self._trade_stop_price is None:
            return None

        direction = self._trade_direction
        close_type = SignalType.CLOSE_LONG if direction == "long" else SignalType.CLOSE_SHORT

        if direction == "long":
            if current_price_f <= self._trade_stop_price:
                self._reset_trade_state()
                return Signal(
                    signal_type=close_type, pair="",
                    timestamp=current_time,
                    price=Decimal(str(current_price_f)),
                    confidence=Decimal("1.0"),
                    metadata={"reason": "atr_stop_loss"},
                )
            if self._trade_take_price and current_price_f >= self._trade_take_price:
                self._reset_trade_state()
                return Signal(
                    signal_type=close_type, pair="",
                    timestamp=current_time,
                    price=Decimal(str(current_price_f)),
                    confidence=Decimal("1.0"),
                    metadata={"reason": "atr_take_profit"},
                )
        elif direction == "short":
            if current_price_f >= self._trade_stop_price:
                self._reset_trade_state()
                return Signal(
                    signal_type=close_type, pair="",
                    timestamp=current_time,
                    price=Decimal(str(current_price_f)),
                    confidence=Decimal("1.0"),
                    metadata={"reason": "atr_stop_loss"},
                )
            if self._trade_take_price and current_price_f <= self._trade_take_price:
                self._reset_trade_state()
                return Signal(
                    signal_type=close_type, pair="",
                    timestamp=current_time,
                    price=Decimal(str(current_price_f)),
                    confidence=Decimal("1.0"),
                    metadata={"reason": "atr_take_profit"},
                )

        return None

    def _set_atr_exit_from_features(
        self,
        features: Dict[str, float],
        direction: str,
        entry_price_f: float,
    ) -> None:
        """Set ATR exit levels from feature dict."""
        if not self.config.use_atr_exit:
            return

        atr_ratio = features.get("atr_ratio", 0)
        atr_f = atr_ratio * entry_price_f
        if atr_f <= 0:
            return

        stop_mult = float(self.config.atr_stop_multiplier)
        take_mult = float(self.config.atr_take_multiplier)

        if direction == "long":
            self._trade_stop_price = entry_price_f - atr_f * stop_mult
            self._trade_take_price = entry_price_f + atr_f * take_mult
        else:
            self._trade_stop_price = entry_price_f + atr_f * stop_mult
            self._trade_take_price = entry_price_f - atr_f * take_mult

        self._trade_direction = direction
        self._trade_entry_price = entry_price_f

    def _reset_trade_state(self) -> None:
        """Clear ATR exit tracking."""
        self._trade_direction = None
        self._trade_entry_price = None
        self._trade_stop_price = None
        self._trade_take_price = None

    def _get_majority_prediction(self) -> int:
        """Get majority vote from recent predictions.

        Returns:
            Most common prediction in the history window
        """
        if not self._prediction_history:
            return 0

        from collections import Counter
        counts = Counter(self._prediction_history)
        return counts.most_common(1)[0][0]

    def _hold_signal(self, context: StrategyContext, reason: str = "") -> Signal:
        """Generate a HOLD signal with reason."""
        return Signal(
            signal_type=SignalType.HOLD,
            pair=context.pair,
            timestamp=context.current_time,
            price=context.current_price,
            confidence=Decimal("0"),
            metadata={"reason": reason, "strategy": "ml_predictor"},
        )

    def validate_params(self) -> List[str]:
        """Validate strategy parameters."""
        errors: List[str] = []

        if self.config.horizon < 1:
            errors.append("horizon must be at least 1")

        if self.config.threshold <= 0:
            errors.append("threshold must be positive")

        if not (0 < float(self.config.confidence_threshold) < 1):
            errors.append("confidence_threshold must be between 0 and 1")

        if self.config.model_type not in ("xgboost", "lightgbm"):
            errors.append("model_type must be 'xgboost' or 'lightgbm'")

        if self.config.atr_period < 2:
            errors.append("atr_period must be at least 2")

        return errors

    def reset(self) -> None:
        """Reset strategy state."""
        super().reset()
        self._reset_trade_state()
        self._prediction_history.clear()
        self._current_regime = MarketRegime.UNKNOWN
        self._model_ready = False
