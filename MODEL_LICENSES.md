# Model acquisition and licensing

`scripts/download_models.py` downloads only the pinned artifacts named in
`THIRD_PARTY_NOTICES.md` and writes `models/model-manifest.json`. The manifest is evidence of
the exact upstream revision and SHA-256 of each downloaded file; it is not a substitute for
the upstream license terms.

## Mandarin text-to-speech: sherpa-onnx `vits-icefall-zh-aishell3`

The Mandarin (`zh-Hans`) voice is the sherpa-onnx VITS model `vits-icefall-zh-aishell3`
(PO decision 2026-11-06, CAP-0169 WI-09). `scripts/download_models.py` downloads exactly this
release archive and refuses any other bytes:

- Source: <https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-icefall-zh-aishell3.tar.bz2>
- Size: 31,559,701 bytes
- SHA-256: `ab468db3a3308cdd861495e0db2f25d79418a0c00639f74944c7cdf5dd8c6ec1`
- Extracted to `models/sherpa/vits-icefall-zh-aishell3/` (`model.onnx`, `lexicon.txt`,
  `tokens.txt`, `phone.fst`, `date.fst`, `number.fst`, `new_heteronym.fst`, `rule.far`,
  `speakers.txt`); each file's SHA-256 is recorded in `models/model-manifest.json`.
- Model: trained with the k2-fsa icefall VITS recipe, Apache-2.0
  (<https://github.com/k2-fsa/icefall>).
- Training data: AISHELL-3 (OpenSLR SLR93), Apache-2.0 (<https://www.openslr.org/93/>).

The archive contains no licence file. The licences above are recorded from the upstream recipe
and dataset; the provenance of the bundled text-normalisation rules (`*.fst`, `rule.far`) and the
lexicon still needs confirming and is tracked in
[#81](https://github.com/boris-heuer/lianiq/issues/81). Keep this file and the manifest with any
redistribution of the voice.

Lianiq uses speaker 20 (`SSB0193`) with deterministic synthesis (`noise_scale=0`,
`noise_scale_w=0`, `length_scale=1.15`), peak normalisation to 0.9, on the CPU with 4 threads.
The voice is 8 kHz; the PO accepted this quality as interim, and the improvement is #81.

The previously configured `zh_CN-huayan-medium` Piper voice stays excluded because a sufficiently
clear dataset/model redistribution license was not established for this project. An operator may
still use another, licence-reviewed Piper voice: set `tts.voices["zh-Hans"]` to its `.onnx` path
(with the matching `.onnx.json` next to it) and `tts.engines["zh-Hans"].engine` to `"piper"`.
Do not infer redistribution permission from a package license or the repository hosting a voice.

The application remains usable with text output if the voice is absent; attempting to
synthesize Mandarin speech without it fails with the existing actionable missing-model error.
