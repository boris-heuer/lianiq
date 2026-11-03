# Changelog

All notable user-visible changes are documented here.

## Unreleased

### Added

- A sanitized application screenshot, repository-owned Markdown link validation, and a fail-closed
  Windows audio troubleshooting matrix.
- A Call Bridge compatibility matrix that separates design compatibility, real-call evidence, and
  production `SystemOK` for headsets and communication applications.

### Changed

- Settings use schema v2: language pair, routing and output in a `languages` block, translation
  models as directed `translation.edges`, voices in `tts.voices` by language ID, and
  `call_bridge.local_language`. Existing settings migrate without loss on load, and the first save
  keeps the original `config/settings.local.json` once as `config/settings.local.v1.json`.
- Models load on **Start**, only for the selected mode: no model loads at application start,
  text output never loads a voice, and a fixed direction loads only its own recognition and
  translation models. A missing reverse translation model raises an error naming that direction
  instead of using another model. A turn in a language outside German/Mandarin is reported and not
  translated; the script-based language guess was removed. `config/glossary.json` is keyed by
  direction (`de>zh-Hans`, `zh-Hans>de`); legacy `de-zh`/`zh-de` keys still load.
- A conversation session keeps the language pair and routing selected at **Start**: the routing
  control and *Switch direction* are disabled until **Stop**, and **Start** is refused with
  "Not available: missing …" when a model the mode needs is missing. Automatic routes each turn
  only to a detected German or Mandarin language at or above `languages.detection_min_probability`
  (0.7); any other turn is held, not translated, and discarded on **Stop**. **Stop** finishes the
  already-queued turns with their original languages and clears the translation context.
  **Export transcript** writes format v2 (`# lianiq transcript v2`, language IDs per turn, ordered
  by capture time).
- Renamed the product, repository metadata, Python package, command, Windows executable, and
  documentation to `lianiq`.

## 0.1.0 - 2026-10-06

### Added

- Public contribution, conduct, support, security, citation, and AI-assisted development guidance.
- An engineering case study that separates automated evidence from pending hardware and call gates.

### Changed

- Public documentation now describes translation as near-real-time and utterance-based.
- Call Bridge documentation identifies the feature as experimental until packaged hardware and
  WeChat acceptance checks are complete.

- Local Windows German/Mandarin speech transcription, translation, and synthesis workflow.
- Experimental, disabled-by-default Call Bridge source implementation.

This file records repository changes, not compatibility, quality, or production-readiness claims.
