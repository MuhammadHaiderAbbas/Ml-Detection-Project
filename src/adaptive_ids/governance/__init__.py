"""Model governance: the documented protocol a candidate must pass before approval."""

from .compare import Comparison, compare_models
from .protocol import EvaluationProtocol, ProtocolError, load_protocol

__all__ = ["Comparison", "EvaluationProtocol", "ProtocolError", "compare_models", "load_protocol"]
