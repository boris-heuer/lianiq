from __future__ import annotations

import pytest

from lianiq.hardware import resolve_compute_device, resolve_onnx_device


@pytest.mark.parametrize("resolver", [resolve_compute_device, resolve_onnx_device])
def test_auto_selects_available_cuda(resolver) -> None:
    assert resolver("auto", available=True) == "cuda"


@pytest.mark.parametrize("resolver", [resolve_compute_device, resolve_onnx_device])
def test_auto_falls_back_to_cpu(resolver) -> None:
    assert resolver("auto", available=False) == "cpu"


@pytest.mark.parametrize("resolver", [resolve_compute_device, resolve_onnx_device])
def test_explicit_cuda_falls_back_when_unavailable(resolver) -> None:
    assert resolver("cuda", available=False) == "cpu"


@pytest.mark.parametrize("resolver", [resolve_compute_device, resolve_onnx_device])
def test_cpu_is_always_honored(resolver) -> None:
    assert resolver("cpu", available=True) == "cpu"


@pytest.mark.parametrize("resolver", [resolve_compute_device, resolve_onnx_device])
def test_invalid_device_is_rejected(resolver) -> None:
    with pytest.raises(ValueError):
        resolver("directml", available=False)
