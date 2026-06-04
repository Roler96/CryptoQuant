"""Model management for ML trading strategies.

Handles training, saving, loading, and inference for gradient boosting
models (XGBoost/LightGBM). Supports:
- Online training from historical data
- Walk-forward cross-validation
- Model persistence (save/load)
- Feature importance analysis
- Prediction with confidence estimation
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import structlog

from data.repository import get_repository
from strategy.ml.feature_engineer import FeatureConfig, FeatureEngineer

logger = structlog.get_logger(__name__)

# Default model directory
MODELS_DIR = Path("models")


def _safe_import_xgboost():
    """Lazily import xgboost, raise helpful error if missing."""
    try:
        import xgboost as xgb
        return xgb
    except ImportError:
        raise ImportError(
            "xgboost is required for ML strategies. "
            "Install with: pip install xgboost"
        )


def _safe_import_lightgbm():
    """Lazily import lightgbm, raise helpful error if missing."""
    try:
        import lightgbm as lgb
        return lgb
    except ImportError:
        raise ImportError(
            "lightgbm is required for LightGBM-based strategies. "
            "Install with: pip install lightgbm"
        )


class TrainingData:
    """Container for prepared ML training data.

    Attributes:
        X: Feature matrix (n_samples, n_features)
        y: Target vector (n_samples,)
        feature_names: Ordered list of feature column names
        timestamps: Sample timestamps for time-aware splitting
        pair: Trading pair used for training
        timeframe: Timeframe used for training
    """

    def __init__(
        self,
        X: np.ndarray,
        y: np.ndarray,
        feature_names: List[str],
        timestamps: Optional[np.ndarray] = None,
        pair: str = "",
        timeframe: str = "",
    ) -> None:
        self.X = X
        self.y = y
        self.feature_names = feature_names
        self.timestamps = timestamps
        self.pair = pair
        self.timeframe = timeframe

    @property
    def n_samples(self) -> int:
        return len(self.y)

    @property
    def n_features(self) -> int:
        return self.X.shape[1] if len(self.X.shape) > 1 else 0

    def split_time_series(
        self, train_ratio: float = 0.7, val_ratio: float = 0.15,
    ) -> Tuple["TrainingData", "TrainingData", "TrainingData"]:
        """Split data chronologically into train/val/test.

        Args:
            train_ratio: Fraction for training set
            val_ratio: Fraction for validation set (test = 1 - train - val)

        Returns:
            Tuple of (train, val, test) TrainingData
        """
        n = self.n_samples
        train_end = int(n * train_ratio)
        val_end = int(n * (train_ratio + val_ratio))

        train = TrainingData(
            X=self.X[:train_end],
            y=self.y[:train_end],
            feature_names=self.feature_names,
            timestamps=self.timestamps[:train_end] if self.timestamps is not None else None,
            pair=self.pair,
            timeframe=self.timeframe,
        )
        val = TrainingData(
            X=self.X[train_end:val_end],
            y=self.y[train_end:val_end],
            feature_names=self.feature_names,
            timestamps=self.timestamps[train_end:val_end] if self.timestamps is not None else None,
            pair=self.pair,
            timeframe=self.timeframe,
        )
        test = TrainingData(
            X=self.X[val_end:],
            y=self.y[val_end:],
            feature_names=self.feature_names,
            timestamps=self.timestamps[val_end:] if self.timestamps is not None else None,
            pair=self.pair,
            timeframe=self.timeframe,
        )
        return train, val, test


class ModelManager:
    """Manages ML model lifecycle for trading strategies.

    Handles:
    - Feature extraction and label generation from OHLCV data
    - Model training with time-series-aware validation
    - Model persistence (save/load with metadata)
    - Inference with confidence estimation
    - Feature importance reporting

    Usage:
        manager = ModelManager()
        data = manager.prepare_training_data("BTC/USDT", "1h", horizon=5)
        model_info = manager.train(data, model_type="xgboost")
        prediction = manager.predict(features_dict)
    """

    def __init__(
        self,
        feature_config: Optional[FeatureConfig] = None,
        models_dir: Optional[Path] = None,
    ) -> None:
        self.feature_engineer = FeatureEngineer(feature_config)
        self.feature_config = feature_config or FeatureConfig()
        self.models_dir = models_dir or MODELS_DIR
        self.model: Optional[Any] = None
        self.model_type: Optional[str] = None
        self.model_info: Optional[Dict[str, Any]] = None
        self.logger = structlog.get_logger(__name__)

    def prepare_training_data(
        self,
        pair: str,
        timeframe: str,
        horizon: int = 5,
        threshold: float = 0.001,
        since: Optional[int] = None,
        until: Optional[int] = None,
    ) -> Optional[TrainingData]:
        """Prepare training data from historical OHLCV.

        Generates labels based on forward returns:
        - 1 (UP):   forward return > +threshold
        - -1 (DOWN): forward return < -threshold
        - 0 (FLAT): between -threshold and +threshold

        Args:
            pair: Trading pair (e.g., "BTC/USDT")
            timeframe: Candle timeframe (e.g., "1h")
            horizon: Forward-looking periods for label generation
            threshold: Minimum return magnitude for UP/DOWN labels
            since: Optional start timestamp
            until: Optional end timestamp

        Returns:
            TrainingData object, or None if insufficient data
        """
        repo = get_repository()
        df = repo.load_as_dataframe(pair, timeframe, since=since, until=until)

        if df.empty:
            self.logger.error("no_data", pair=pair, timeframe=timeframe)
            return None

        min_rows = self.feature_config.min_candles + horizon + 10
        if len(df) < min_rows:
            self.logger.error(
                "insufficient_data",
                rows=len(df),
                required=min_rows,
            )
            return None

        self.logger.info(
            "preparing_training_data",
            pair=pair,
            timeframe=timeframe,
            rows=len(df),
            horizon=horizon,
            threshold=threshold,
        )

        # Extract features for each bar (rolling window)
        closes = df["close"].values.astype(float)
        opens = df["open"].values.astype(float)
        highs = df["high"].values.astype(float)
        lows = df["low"].values.astype(float)
        volumes = df["volume"].values.astype(float)
        timestamps = df["timestamp"].values.astype(float)

        feature_names = self.feature_engineer.get_feature_names()
        all_features: List[List[float]] = []
        all_labels: List[int] = []
        all_timestamps: List[float] = []

        # Skip first min_candles (not enough for indicators)
        # Skip last horizon (no forward label)
        start_idx = self.feature_config.min_candles
        end_idx = len(closes) - horizon

        for i in range(start_idx, end_idx):
            # Feature extraction on window [0:i+1]
            window_closes = closes[:i + 1].tolist()
            window_opens = opens[:i + 1].tolist()
            window_highs = highs[:i + 1].tolist()
            window_lows = lows[:i + 1].tolist()
            window_volumes = volumes[:i + 1].tolist()

            features = self.feature_engineer.extract_f(
                window_opens, window_highs, window_lows,
                window_closes, window_volumes,
            )
            if features is None:
                continue

            # Label: forward return over horizon periods
            forward_return = (closes[i + horizon] - closes[i]) / closes[i]

            if forward_return > threshold:
                label = 1   # UP
            elif forward_return < -threshold:
                label = -1  # DOWN
            else:
                label = 0   # FLAT

            all_features.append(self.feature_engineer.features_to_vector(features))
            all_labels.append(label)
            all_timestamps.append(timestamps[i])

        if len(all_features) < 100:
            self.logger.error("too_few_samples", n=len(all_features))
            return None

        X = np.array(all_features, dtype=np.float32)
        y = np.array(all_labels, dtype=np.int32)
        ts = np.array(all_timestamps, dtype=np.float64)

        # Replace NaN/Inf with 0
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

        self.logger.info(
            "training_data_prepared",
            n_samples=len(y),
            n_features=X.shape[1],
            label_distribution=dict(zip(*np.unique(y, return_counts=True))),
        )

        return TrainingData(
            X=X, y=y,
            feature_names=feature_names,
            timestamps=ts,
            pair=pair,
            timeframe=timeframe,
        )

    def train(
        self,
        data: TrainingData,
        model_type: str = "xgboost",
        params: Optional[Dict[str, Any]] = None,
        train_ratio: float = 0.7,
        val_ratio: float = 0.15,
    ) -> Dict[str, Any]:
        """Train ML model on prepared data.

        Args:
            data: Prepared TrainingData
            model_type: "xgboost" or "lightgbm"
            params: Model hyperparameters (overrides defaults)
            train_ratio: Fraction for training
            val_ratio: Fraction for validation

        Returns:
            Dictionary with training results and metrics
        """
        train, val, test = data.split_time_series(train_ratio, val_ratio)

        self.logger.info(
            "starting_training",
            model_type=model_type,
            train_samples=train.n_samples,
            val_samples=val.n_samples,
            test_samples=test.n_samples,
        )

        if model_type == "xgboost":
            model, metrics = self._train_xgboost(train, val, test, params)
        elif model_type == "lightgbm":
            model, metrics = self._train_lightgbm(train, val, test, params)
        else:
            raise ValueError(f"Unsupported model_type: {model_type}. Use 'xgboost' or 'lightgbm'.")

        self.model = model
        self.model_type = model_type

        self.model_info = {
            "model_type": model_type,
            "pair": data.pair,
            "timeframe": data.timeframe,
            "n_features": data.n_features,
            "feature_names": data.feature_names,
            "train_samples": train.n_samples,
            "val_samples": val.n_samples,
            "test_samples": test.n_samples,
            "train_time": datetime.now().isoformat(),
            "metrics": metrics,
        }

        self.logger.info("training_complete", metrics=metrics)
        return self.model_info

    def _train_xgboost(
        self,
        train: TrainingData,
        val: TrainingData,
        test: TrainingData,
        params: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Any, Dict[str, Any]]:
        """Train XGBoost classifier."""
        xgb = _safe_import_xgboost()

        default_params = {
            "n_estimators": 300,
            "max_depth": 5,
            "learning_rate": 0.05,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "min_child_weight": 10,
            "reg_alpha": 0.1,
            "reg_lambda": 1.0,
            "objective": "multi:softprob",
            "num_class": 3,
            "eval_metric": "mlogloss",
            "verbosity": 0,
            "random_state": 42,
        }
        if params:
            default_params.update(params)

        # Map labels: -1->0, 0->1, 1->2 for XGBoost multi-class
        y_train_mapped = train.y + 1
        y_val_mapped = val.y + 1

        model = xgb.XGBClassifier(**default_params)
        model.fit(
            train.X, y_train_mapped,
            eval_set=[(val.X, y_val_mapped)],
            verbose=False,
        )

        # Evaluate
        metrics = self._evaluate_model(model, test, label_shift=1)
        return model, metrics

    def _train_lightgbm(
        self,
        train: TrainingData,
        val: TrainingData,
        test: TrainingData,
        params: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Any, Dict[str, Any]]:
        """Train LightGBM classifier."""
        lgb = _safe_import_lightgbm()

        default_params = {
            "n_estimators": 300,
            "max_depth": 5,
            "learning_rate": 0.05,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "min_child_samples": 20,
            "reg_alpha": 0.1,
            "reg_lambda": 1.0,
            "objective": "multiclass",
            "num_class": 3,
            "verbosity": -1,
            "random_state": 42,
        }
        if params:
            default_params.update(params)

        y_train_mapped = train.y + 1
        y_val_mapped = val.y + 1

        model = lgb.LGBMClassifier(**default_params)
        model.fit(
            train.X, y_train_mapped,
            eval_set=[(val.X, y_val_mapped)],
            callbacks=[lgb.logging.log_evaluation(period=0)],
        )

        metrics = self._evaluate_model(model, test, label_shift=1)
        return model, metrics

    def _evaluate_model(
        self,
        model: Any,
        test: TrainingData,
        label_shift: int = 0,
    ) -> Dict[str, Any]:
        """Evaluate model on test set."""
        y_test_mapped = test.y + label_shift
        y_pred = model.predict(test.X)
        y_proba = model.predict_proba(test.X)

        accuracy = np.mean(y_pred == y_test_mapped)

        # Per-class accuracy
        unique_labels = np.unique(y_test_mapped)
        per_class_acc = {}
        for label in unique_labels:
            mask = y_test_mapped == label
            if mask.sum() > 0:
                label_name = {0: "DOWN", 1: "FLAT", 2: "UP"}.get(int(label), str(label))
                per_class_acc[label_name] = float(np.mean(y_pred[mask] == label))

        # Directional accuracy (ignoring FLAT)
        non_flat_mask = y_test_mapped != 1  # 1 is FLAT after shift
        if non_flat_mask.sum() > 0:
            directional_acc = float(np.mean(y_pred[non_flat_mask] == y_test_mapped[non_flat_mask]))
        else:
            directional_acc = 0.0

        # Log loss
        try:
            from sklearn.metrics import log_loss
            ll = log_loss(y_test_mapped, y_proba, labels=list(range(max(y_test_mapped) + 1)))
        except (ImportError, ValueError):
            ll = None

        return {
            "accuracy": float(accuracy),
            "directional_accuracy": directional_acc,
            "per_class_accuracy": per_class_acc,
            "log_loss": ll,
            "test_samples": test.n_samples,
        }

    def predict(self, features: Dict[str, float]) -> Tuple[int, float, Dict[int, float]]:
        """Make prediction from feature dict.

        Args:
            features: Feature dictionary from FeatureEngineer

        Returns:
            Tuple of (predicted_label, confidence, class_probabilities)
            - predicted_label: -1 (DOWN), 0 (FLAT), 1 (UP)
            - confidence: Max class probability
            - class_probabilities: {0: prob_down, 1: prob_flat, 2: prob_up}
        """
        if self.model is None:
            return 0, 0.33, {0: 0.33, 1: 0.34, 2: 0.33}

        vector = self.feature_engineer.features_to_vector(features)
        X = np.array([vector], dtype=np.float32)
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

        y_pred_mapped = self.model.predict(X)[0]
        y_proba = self.model.predict_proba(X)[0]

        # Map back: 0->-1, 1->0, 2->1
        label_map = {0: -1, 1: 0, 2: 1}
        predicted_label = label_map.get(int(y_pred_mapped), 0)
        confidence = float(max(y_proba))

        class_probs = {
            -1: float(y_proba[0]),
            0: float(y_proba[1]),
            1: float(y_proba[2]),
        }

        return predicted_label, confidence, class_probs

    def predict_vector(self, X: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Batch prediction on feature matrix.

        Args:
            X: Feature matrix (n_samples, n_features)

        Returns:
            Tuple of (labels_mapped, probabilities)
        """
        if self.model is None:
            raise RuntimeError("No model loaded. Call train() or load_model() first.")

        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
        y_pred = self.model.predict(X)
        y_proba = self.model.predict_proba(X)
        return y_pred, y_proba

    def get_feature_importance(self, top_n: int = 20) -> List[Tuple[str, float]]:
        """Get feature importance from trained model.

        Args:
            top_n: Number of top features to return

        Returns:
            List of (feature_name, importance_score) sorted by importance
        """
        if self.model is None:
            return []

        if hasattr(self.model, "feature_importances_"):
            importances = self.model.feature_importances_
        else:
            return []

        feature_names = self.model_info.get("feature_names", []) if self.model_info else []
        if not feature_names:
            feature_names = [f"f{i}" for i in range(len(importances))]

        paired = list(zip(feature_names, importances))
        paired.sort(key=lambda x: x[1], reverse=True)
        return paired[:top_n]

    def save_model(self, name: Optional[str] = None) -> str:
        """Save trained model and metadata to disk.

        Args:
            name: Model name (auto-generated if None)

        Returns:
            Path to saved model directory
        """
        if self.model is None:
            raise RuntimeError("No model to save. Train first.")

        self.models_dir.mkdir(parents=True, exist_ok=True)

        if name is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            pair = self.model_info.get("pair", "unknown").replace("/", "_") if self.model_info else "unknown"
            name = f"ml_{pair}_{timestamp}"

        model_dir = self.models_dir / name
        model_dir.mkdir(parents=True, exist_ok=True)

        # Save model
        if self.model_type == "xgboost":
            self.model.save_model(str(model_dir / "model.json"))
        elif self.model_type == "lightgbm":
            self.model.booster_.save_model(str(model_dir / "model.txt"))

        # Save metadata
        meta = dict(self.model_info) if self.model_info else {}
        meta["model_type"] = self.model_type
        with open(model_dir / "metadata.json", "w") as f:
            json.dump(meta, f, indent=2, default=str)

        self.logger.info("model_saved", path=str(model_dir))
        return str(model_dir)

    def load_model(self, model_dir: str) -> None:
        """Load trained model from disk.

        Args:
            model_dir: Path to model directory
        """
        model_path = Path(model_dir)

        with open(model_path / "metadata.json", "r") as f:
            meta = json.load(f)

        model_type = meta.get("model_type", "xgboost")

        if model_type == "xgboost":
            xgb = _safe_import_xgboost()
            model = xgb.XGBClassifier()
            model.load_model(str(model_path / "model.json"))
        elif model_type == "lightgbm":
            lgb = _safe_import_lightgbm()
            model = lgb.LGBMClassifier()
            model.booster_ = lgb.Booster(model_file=str(model_path / "model.txt"))
        else:
            raise ValueError(f"Unknown model type: {model_type}")

        self.model = model
        self.model_type = model_type
        self.model_info = meta

        self.logger.info("model_loaded", path=model_dir, model_type=model_type)

    def walk_forward_validate(
        self,
        data: TrainingData,
        n_splits: int = 5,
        model_type: str = "xgboost",
        params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Walk-forward cross-validation for time series.

        Expanding window: each fold uses more historical data for training.

        Args:
            data: Full training data
            n_splits: Number of CV folds
            model_type: Model type to use
            params: Model parameters

        Returns:
            List of metric dictionaries for each fold
        """
        n = data.n_samples
        fold_size = n // (n_splits + 1)
        results = []

        for i in range(n_splits):
            train_end = fold_size * (i + 1) + fold_size  # expanding window
            val_end = min(train_end + fold_size, n)

            if val_end > n:
                break

            train = TrainingData(
                X=data.X[:train_end],
                y=data.y[:train_end],
                feature_names=data.feature_names,
                pair=data.pair,
                timeframe=data.timeframe,
            )
            val = TrainingData(
                X=data.X[train_end:val_end],
                y=data.y[train_end:val_end],
                feature_names=data.feature_names,
                pair=data.pair,
                timeframe=data.timeframe,
            )
            test = val  # Use val as test for this fold

            if model_type == "xgboost":
                _, metrics = self._train_xgboost(train, val, test, params)
            else:
                _, metrics = self._train_lightgbm(train, val, test, params)

            metrics["fold"] = i + 1
            metrics["train_size"] = train_end
            results.append(metrics)

            self.logger.info(
                "walk_forward_fold",
                fold=i + 1,
                accuracy=metrics.get("accuracy", 0),
            )

        avg_accuracy = np.mean([r.get("accuracy", 0) for r in results]) if results else 0
        self.logger.info("walk_forward_complete", n_folds=len(results), avg_accuracy=avg_accuracy)

        return results
