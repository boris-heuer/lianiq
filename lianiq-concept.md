# Historical Project Concept for lianiq

> This is the original aspirational concept, retained as design history. It is not the current
> product specification or evidence of delivered behavior. The [README](README.md),
> [engineering case study](docs/engineering-case-study.md), and
> [Call Bridge evidence](docs/call-bridge-system-ok.md) describe the implemented scope and limits.

## Goal

Develop a fully local Windows application that translates live conversations between German and
Mandarin Chinese. The application must not use cloud services and must remain fully functional
offline. Its primary objective is low latency so that two people can hold a natural conversation
with the software acting as an interpreter.

## Core requirements

### Speech input

- Microphone capture
- Continuous listening
- Automatic pause detection
- German and Mandarin Chinese support

### Offline speech-to-text

Preferred engine: Faster-Whisper, with Whisper as a fallback.

- Real-time transcription
- High accuracy
- Short audio chunks
- Streaming behavior

### Translation

Preferred engines, in order: Meta SeamlessM4T, Meta NLLB-200, and MarianMT as a fallback.

- German to Mandarin
- Mandarin to German
- Fully offline execution
- Multi-sentence conversational context
- Optional terminology glossaries

### Speech synthesis

Preferred engine: Piper TTS. Alternatives are Coqui TTS and XTTS.

- Natural voices
- German output
- Mandarin output
- Offline execution

### Bidirectional conversation

- Mode A: German speech to Mandarin output
- Mode B: Mandarin speech to German output
- Optional automatic language detection and switching

## Target architecture

```text
Microphone
    -> Audio buffer
    -> Faster-Whisper
    -> Language recognition
    -> SeamlessM4T or NLLB
    -> Translation
    -> Piper TTS
    -> Speakers
```

## Technical requirements

- Python 3.12
- Modern desktop UI
- PySide6 preferred; Qt or Tkinter only if required

## User interface

The main window presents the original text and translation side by side, for example:

```text
DE: Guten Tag, wie geht es Ihnen?
ZH: 您好，您好吗？
```

Controls:

- Start
- Stop
- Switch language
- Select microphone
- Select speakers
- Select model
- Set target language
- Enable or disable TTS
- Enable GPU mode

## Performance targets

| Stage | Target |
|---|---:|
| Speech-to-text | under 1 second |
| Translation | under 0.5 seconds |
| TTS | under 0.5 seconds |
| End to end | 1 to 3 seconds |

Use CUDA and the PyTorch CUDA backend when an NVIDIA GPU is present. Fall back to CPU
automatically when no supported GPU is available.

## Suggested project structure

```text
lianiq/
|-- main.py
|-- ui/
|   `-- main_window.py
|-- audio/
|   `-- microphone.py
|-- stt/
|   `-- whisper_engine.py
|-- translation/
|   `-- seamlessm4t.py
|-- tts/
|   `-- piper_engine.py
|-- config/
|   `-- settings.json
`-- models/
```

## Optional enhancements

- Retain the last five to ten sentences as conversation context.
- Export timestamped original and translated text to TXT or PDF.
- Use `F8` to start and `F9` to stop.
- Offer live subtitle overlays over other applications.

## Deliverables

1. Complete source code
2. `requirements-lock.txt`
3. Installation guide
4. Windows build guide
5. Step-by-step explanation
6. Performance optimizations
7. Error handling
8. Logging

This was the original target: production-ready, modular, maintainable, local, privacy-preserving,
and one-to-three-second utterance latency. The current prototype does not claim that every target
has been met; use the current evidence documents linked above for status.
