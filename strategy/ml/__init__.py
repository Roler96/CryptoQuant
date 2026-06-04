"""Machine Learning strategies for CryptoQuant platform.

This module contains ML-based trading strategies:
- PricePredictorStrategy: Gradient boosting price direction prediction
- FeatureEngineer: Technical + statistical feature extraction
- ModelManager: Model training, persistence, and inference
"""

from strategy.ml.price_predictor import PricePredictorStrategy
from strategy.ml.feature_engineer import FeatureEngineer
from strategy.ml.model_manager import ModelManager

__all__ = [
    "PricePredictorStrategy",
    "FeatureEngineer",
    "ModelManager",
]
