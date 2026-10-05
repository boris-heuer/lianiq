from __future__ import annotations

import logging

LOGGER = logging.getLogger(__name__)


def torch_cuda_available() -> bool:
    try:
        import torch

        return torch.cuda.is_available()
    except (ImportError, RuntimeError):
        return False


def ctranslate2_cuda_available() -> bool:
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except (ImportError, RuntimeError):
        return False


def onnx_cuda_available() -> bool:
    try:
        import onnxruntime

        return "CUDAExecutionProvider" in onnxruntime.get_available_providers()
    except (ImportError, RuntimeError):
        return False


def resolve_compute_device(requested: str, available: bool | None = None) -> str:
    normalized = requested.strip().lower()
    if normalized not in {"auto", "cpu", "cuda"}:
        raise ValueError(f"Unsupported compute device: {requested}")
    has_cuda = torch_cuda_available() if available is None else available
    if normalized == "cpu":
        return "cpu"
    if has_cuda:
        return "cuda"
    if normalized == "cuda":
        LOGGER.warning("CUDA was requested but is unavailable; falling back to CPU")
    return "cpu"


def resolve_onnx_device(requested: str, available: bool | None = None) -> str:
    normalized = requested.strip().lower()
    if normalized not in {"auto", "cpu", "cuda"}:
        raise ValueError(f"Unsupported ONNX device: {requested}")
    has_cuda = onnx_cuda_available() if available is None else available
    if normalized == "cpu":
        return "cpu"
    if has_cuda:
        return "cuda"
    if normalized == "cuda":
        LOGGER.warning("ONNX CUDA was requested but is unavailable; falling back to CPU")
    return "cpu"
