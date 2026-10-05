# Offline German-Mandarin Interpreter

A fully local Windows application for real-time conversations between German and Mandarin
Chinese. Microphone audio, transcription, translation, speech synthesis, and transcripts stay
on the device. After the one-time model download, the application requires no network access.

## Target hardware

The default profile is tuned for the detected **HP EliteBook 8 G1a 16-inch Notebook Next Gen
AI PC**:

- AMD Ryzen AI 7 350, 8 cores / 16 threads
- 64 GB RAM
- AMD Radeon 860M without CUDA support
- Windows 11 Pro and Python 3.12

Faster-Whisper `small` therefore runs through CTranslate2 with CPU INT8 and eight worker
threads. MarianMT also uses eight CPU threads. The integrated Radeon is deliberately not routed
through an unreliable CUDA compatibility layer. Measure actual latency on this device with
`scripts/benchmark.py`.

The default `auto` device setting selects CUDA independently for CTranslate2, PyTorch, and ONNX
Runtime when each backend reports a usable NVIDIA GPU. Any unavailable backend falls back to the
CPU, so a partial or missing CUDA installation does not prevent the application from starting.

## Architecture

```text
Microphone (16 kHz mono)
  -> energy-based speech and pause detection
  -> bounded real-time queue
  -> Faster-Whisper small (CPU INT8)
  -> MarianMT de <-> zh
  -> Piper TTS
  -> selected speakers
```

Microphone processing is muted while Piper speaks, preventing the application from translating
its own output. If the bounded queue fills, the oldest pending segment is dropped to prevent the
conversation from accumulating increasing delay.

Automatic mode detects and routes every completed utterance independently. It never assumes that
participants alternate, so any number of German or Mandarin turns may occur consecutively. See
[`docs/conversation-architecture.md`](docs/conversation-architecture.md) for multi-participant
scenarios, overlap limitations, and the TDD strategy.

## Planned call bridge

The planned full-duplex call bridge will place the application between a local headset and a call
application such as WeChat. Two independent, fixed-direction translation lanes will connect the
physical headset to two virtual audio cables without exposing the physical microphone directly to
the call application.

- [`docs/call-bridge-architecture.md`](docs/call-bridge-architecture.md) defines the technical
  architecture and audio routing decisions.
- [`docs/call-bridge-implementation-plan.md`](docs/call-bridge-implementation-plan.md) defines the
  TDD work order, synthetic scenarios, and acceptance gates.
- [`docs/call-bridge-operator-setup.md`](docs/call-bridge-operator-setup.md) defines the proposed
  Windows and WeChat device mapping. The feature is not implemented yet.

## Windows installation

Run in PowerShell from the project directory:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup.ps1
```

The script:

1. creates a Python 3.12 virtual environment in `.venv`,
2. installs the application and its dependencies,
3. downloads Faster-Whisper, both MarianMT models, and both Piper voices,
4. validates the installation with the offline doctor.

Model download is the only step that requires internet access. Existing downloads are reused
from the Hugging Face cache. To validate an existing installation without requesting models:

```powershell
.\.venv\Scripts\python.exe .\scripts\doctor.py
```

## Run

```powershell
.\.venv\Scripts\python.exe -m offline_translator
```

- `F8`: start capture
- `F9`: stop capture
- Choose automatic direction, German to Mandarin, or Mandarin to German.
- Select microphone and speakers before starting.
- Disable or enable spoken output at any time.

Models are loaded into memory when first needed, so the first request is slower than subsequent
requests.

## Measure latency

Use a 16 kHz mono PCM16 WAV file with a spoken test sentence:

```powershell
.\.venv\Scripts\python.exe .\scripts\benchmark.py .\testdata\german.wav --mode de-zh
.\.venv\Scripts\python.exe .\scripts\benchmark.py .\testdata\mandarin.wav --mode zh-de
```

The benchmark returns exit code `0` when end-to-end processing, including voice output, takes no
more than three seconds. Use `--without-tts` to measure STT and translation only.

Run the fully offline synthetic self-test to exercise both language directions through real STT,
translation, and TTS models without requiring a person to speak:

```powershell
.\.venv\Scripts\python.exe .\scripts\self_test.py
.\.venv\Scripts\python.exe .\scripts\ui_self_test.py
```

The UI self-test opens the real application window, starts the microphone, injects deterministic
speech, renders the result, plays the translated voice, and closes after a successful turn.

## Configuration and glossary

[`config/settings.json`](config/settings.json) contains audio thresholds, device selection, model
paths, and thread counts. Define domain terminology in
[`config/glossary.json`](config/glossary.json):

```json
{
  "de-zh": {
    "Ryzen AI": "锐龙 AI"
  },
  "zh-de": {
    "人工智能": "artificial intelligence"
  }
}
```

Longer glossary terms are replaced before shorter ones. The pipeline retains the last five
conversation entries. MarianMT translates the current sentence only for predictable latency and
quality; the context interface allows a later context-aware engine without changing capture or UI
code.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
```

The test suite covers configuration, speech segmentation, direction handling, context buffering,
and glossary processing without requiring a microphone.

## Windows build

```powershell
.\scripts\build.ps1
```

The result is written to `dist\OfflineInterpreter`. The folder contains the application,
configuration, and local models. A directory build is used intentionally because it starts faster
and handles the large model files more predictably than a single executable.

## Privacy and diagnostics

- Runtime code makes no network requests; all model loaders use local paths only.
- Transcript export happens only after the user chooses a local destination.
- Rotating logs are stored in `logs\offline-interpreter.log` and never contain audio.
- Native faults are written to `logs\native-crash.log`; Qt uses software rendering for stability
  on the integrated Radeon GPU.
- Missing dependencies and models produce actionable error messages.
- `scripts\doctor.py` validates dependencies and every required model file.
- `scripts\self_test.py` validates both complete model pipelines against the three-second target.

## Model sources and licensing

- Speech recognition: `Systran/faster-whisper-small`
- Translation: `Helsinki-NLP/opus-mt-de-zh` and `Helsinki-NLP/opus-mt-zh-de`
- Voices: `rhasspy/piper-voices`, `de_DE-thorsten-medium`, and `zh_CN-huayan-medium`

Review and redistribute all applicable package and model licenses with any binary distribution.
Current Piper releases are GPLv3, which is particularly relevant to commercial distribution.
