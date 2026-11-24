from __future__ import annotations

import logging
import threading
from collections.abc import Iterable, Mapping
from pathlib import Path
from types import MappingProxyType

from lianiq.hardware import resolve_compute_device
from lianiq.languages.capabilities import DirectedEdge
from lianiq.languages.errors import CapabilityMissingError
from lianiq.languages.requirements import Requirement, RequirementKind
from lianiq.translation.glossary import Glossary

LOGGER = logging.getLogger(__name__)


class ModelLoadError(RuntimeError):
    """The translation runtime or a model could not be loaded."""


class MarianTranslator:
    """MarianMT models per directed edge, each loaded on first use or by ``warm_up``.

    An edge without a configured model raises ``CapabilityMissingError``; no other edge
    (in particular not the reverse edge) is used instead. One lock serialises loading,
    tokenising and generation, so Text translation segments interleave safely with
    Conversation turns on another thread (CAP-0172 contract.md §6).
    """

    def __init__(
        self,
        edges: Mapping[DirectedEdge, Path],
        glossary: Glossary,
        cpu_threads: int = 8,
        device: str = "cpu",
        target_prefixes: Mapping[DirectedEdge, str] = MappingProxyType({}),
    ) -> None:
        self.edges = dict(edges)
        # Multi-target models need a sentence-initial ``>>id<<`` token (CAP-0181 §3.3).
        self.target_prefixes = dict(target_prefixes)
        self.glossary = glossary
        self.cpu_threads = cpu_threads
        self.device = resolve_compute_device(device)
        self._loaded: dict[DirectedEdge, tuple[object, object]] = {}
        self._lock = threading.Lock()

    def _load(self, edge: DirectedEdge):
        with self._lock:
            return self._load_locked(edge)

    def _load_locked(self, edge: DirectedEdge):
        if edge in self._loaded:
            return self._loaded[edge]
        path = self.edges.get(edge)
        if path is None:
            raise CapabilityMissingError(Requirement(RequirementKind.TRANSLATION, edge.key))
        if not path.exists():
            raise FileNotFoundError(
                f"Translation model is missing: {path}. Run scripts/download_models.py first."
            )
        try:
            import torch
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        except ImportError as exc:
            raise ModelLoadError("torch/transformers is not installed") from exc
        torch.set_num_threads(self.cpu_threads)
        LOGGER.info("Loading MarianMT for %s from %s", edge.key, path)
        tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)
        model = AutoModelForSeq2SeqLM.from_pretrained(path, local_files_only=True)
        model.to(self.device)
        model.eval()
        self._loaded[edge] = (tokenizer, model)
        return tokenizer, model

    def warm_up(self, edges: Iterable[DirectedEdge]) -> None:
        """Load exactly ``edges`` (the edges the started mode requires)."""
        for edge in edges:
            self._load(edge)

    def translate(
        self,
        text: str,
        edge: DirectedEdge,
        context: tuple[str, ...] = (),
    ) -> str:
        del (
            context
        )  # Marian is sentence-based; history is retained by the pipeline for future engines.
        import torch

        with self._lock:
            tokenizer, model = self._load_locked(edge)
            source = self._source(text, edge)
            inputs = tokenizer(source, return_tensors="pt", truncation=True, max_length=256)
            inputs = {key: value.to(self.device) for key, value in inputs.items()}
            with torch.inference_mode():
                tokens = model.generate(
                    **inputs,
                    num_beams=1,
                    do_sample=False,
                    max_new_tokens=192,
                    renormalize_logits=True,
                )
            translated = tokenizer.batch_decode(tokens, skip_special_tokens=True)[0].strip()
        return self.glossary.apply(translated, edge)

    def token_count(self, text: str, edge: DirectedEdge) -> int:
        """Model input tokens of ``text`` for ``edge``, special tokens included."""
        with self._lock:
            tokenizer, _model = self._load_locked(edge)
            return len(tokenizer(self._source(text, edge), truncation=False)["input_ids"])

    def _source(self, text: str, edge: DirectedEdge) -> str:
        """The model input: ``text`` behind the edge's target prefix, if it has one."""
        prefix = self.target_prefixes.get(edge)
        return f"{prefix} {text}" if prefix else text
