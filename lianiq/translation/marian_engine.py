from __future__ import annotations

import logging
from pathlib import Path

from lianiq.domain import Language
from lianiq.hardware import resolve_compute_device
from lianiq.translation.glossary import Glossary

LOGGER = logging.getLogger(__name__)


class MarianTranslator:
    def __init__(
        self,
        de_zh_path: Path,
        zh_de_path: Path,
        glossary: Glossary,
        cpu_threads: int = 8,
        device: str = "cpu",
    ) -> None:
        self.paths = {
            (Language.GERMAN, Language.MANDARIN): de_zh_path,
            (Language.MANDARIN, Language.GERMAN): zh_de_path,
        }
        self.glossary = glossary
        self.cpu_threads = cpu_threads
        self.device = resolve_compute_device(device)
        self._loaded: dict[tuple[Language, Language], tuple[object, object]] = {}

    def _load(self, source: Language, target: Language):
        key = (source, target)
        if key in self._loaded:
            return self._loaded[key]
        path = self.paths[key]
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
        LOGGER.info("Loading MarianMT from %s", path)
        tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)
        model = AutoModelForSeq2SeqLM.from_pretrained(path, local_files_only=True)
        model.to(self.device)
        model.eval()
        self._loaded[key] = (tokenizer, model)
        return tokenizer, model

    def warm_up(self) -> None:
        self._load(Language.GERMAN, Language.MANDARIN)
        self._load(Language.MANDARIN, Language.GERMAN)

    def translate(
        self,
        text: str,
        source: Language,
        target: Language,
        context: tuple[str, ...] = (),
    ) -> str:
        del (
            context
        )  # Marian is sentence-based; history is retained by the pipeline for future engines.
        tokenizer, model = self._load(source, target)
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
        return self.glossary.apply(translated, source, target)
