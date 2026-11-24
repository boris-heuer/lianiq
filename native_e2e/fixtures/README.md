# Native E2E speech fixtures

Synthetic speech only, 16 kHz mono 16-bit PCM WAV. Each file starts with 0.5 s of silence,
has 1 s of silence between sentences and ends with 1 s of silence. The rows check every file
against the SHA-256 pinned in `native_e2e/fixtures.py` (E-14: in `rows/e14.py`) before they
play it, and add the spoken texts to the redaction secrets.

Regenerate with the voices of an installed models folder (only read):

```powershell
python native_e2e\data\make_fixtures.py --models <models folder> [--only <name> ...]
```

Synthesis is not bit-stable across builds: a regenerated file needs a new pin in
`native_e2e/fixtures.py` and a new SHA-256 below.

## Files

| File | Text | Voice | SHA-256 |
|---|---|---|---|
| `listen_de_16k.wav` | Two German sentences (CAP-0170 E-14) | Piper `de_DE-thorsten-medium` | `b82a5b80f05a5c444b222351875b57e286d456ad2ba927ddd1e057bce702a6cb` |
| `conv_de_16k.wav` | "Guten Morgen, das ist ein Test." | Piper `de_DE-thorsten-medium` | `7874412d2d3972910cd2e73a5c486834d296af2996584a76e3b759cd09b5a858` |
| `listen_de3_16k.wav` | "Guten Morgen." · "Wir liefern die Ware nächste Woche." · "Der Preis enthält die Fracht." | Piper `de_DE-thorsten-medium` | `99010a6c5e3fc064b8fcd1cca3f43c9962c884cf38c47d7ef7f61915b897d793` |
| `listen_sentinel_16k.wav` | "Lianiq Kontrollsatz QX7 Hörprobe." | Piper `de_DE-thorsten-medium` | `1af0f1e0c459eb90591ae4e7485e8aa09ab0b3e1afe5b55c269160aa1eb8bc27` |

Not generated yet (no readable copy of the Mandarin voice on the build host; rows that need
them are `blocked` with `fixture-missing` until a regenerated file is committed and pinned):

| File | Text | Voice |
|---|---|---|
| `conv_zh_16k.wav` | "你好，这是一个测试。" | sherpa-onnx `vits-icefall-zh-aishell3`, speaker 0 |
| `listen_zh_de_16k.wav` | "你好，很高兴见到你。" · "Der Preis enthält die Fracht." | sherpa-onnx `vits-icefall-zh-aishell3`, speaker 0; Piper `de_DE-thorsten-medium` |

## Voice licences

- Piper `de_DE-thorsten-medium` (rhasspy/piper-voices): MIT (repository); the Thorsten
  dataset is CC0 (model card `models/piper/de_DE-thorsten-medium.MODEL_CARD.md`).
- sherpa-onnx `vits-icefall-zh-aishell3` (k2-fsa): Apache-2.0 (icefall VITS recipe; AISHELL-3
  dataset), as recorded in `lianiq/packs/builtin_catalog.json`.

The generated audio holds no recorded human voice and no personal data.
