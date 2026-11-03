from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from pathlib import Path

from lianiq.hardware import resolve_compute_device
from lianiq.languages.capabilities import DirectedEdge
from lianiq.languages.errors import CapabilityMissingError
from lianiq.languages.requirements import Requirement, RequirementKind
from lianiq.translation.glossary import Glossary

LOGGER = logging.getLogger(__name__)


class MarianTranslator:
    """MarianMT models per directed edge, each loaded on first use or by ``warm_up``.

    An edge without a configured model raises ``CapabilityMissingError``; no other edge
    (in particular not the reverse edge) is used instead.
    """

    def __init__(
        self,
        edges: Mapping[DirectedEdge, Path],
        glossary: Glossary,
        cpu_threads: int = 8,
        device: str = "cpu",
    ) -> None:
        self.edges = dict(edges)
        self.glossary = glossary
        self.cpu_threads = cpu_threads
        self.device = resolve_compute_device(device)
        self._loaded: dict[DirectedEdge, tuple[object, object]] = {}

    def _load(self, edge: DirectedEdge):
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
            raise RuntimeError("torch/transformers is not installed") from exc
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
        tokenizer, model = self._load(edge)
        import torch

        inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=256)
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
