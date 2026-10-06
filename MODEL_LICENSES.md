# Model acquisition and licensing

`scripts/download_models.py` downloads only the pinned artifacts named in
`THIRD_PARTY_NOTICES.md` and writes `models/model-manifest.json`. The manifest is evidence of
the exact upstream revision and SHA-256 of each downloaded file; it is not a substitute for
the upstream license terms.

## Mandarin text-to-speech is bring-your-own

No Mandarin voice is downloaded or distributed by this repository. The previously configured
`zh_CN-huayan-medium` voice is deliberately excluded because a sufficiently clear dataset/model
redistribution license was not established for this project.

An operator who enables Mandarin speech must obtain a Piper-compatible `.onnx` voice and its
matching `.onnx.json` metadata, review the voice-model and training-data terms, and set
`tts.zh_voice_path` to the local `.onnx` path. Keep a copy of the relevant license and the
voice source revision with the deployment. Do not infer redistribution permission from the
Piper package license or the repository hosting a voice.

The application remains usable with text output if that optional voice is absent; attempting
to synthesize Mandarin speech without it fails with the existing actionable missing-model error.
