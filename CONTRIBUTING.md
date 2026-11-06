# Contributing

Thanks for improving `lianiq`. Contributions are welcome through focused issues and pull
requests.

## Project language

Use English for all GitHub-visible project content: issue and pull-request titles,
descriptions and comments, documentation, code identifiers and comments, test names,
UI labels, error messages, commit messages and release notes. This applies even when
the working conversation takes place in another language.

Multilingual translation inputs, expected outputs, speech samples and native language
names are functional data and retain their original language. Describe their purpose
and assertions in English; do not include non-English explanatory prose or parenthetical
translations of capability names.

## Before changing code

1. Search open issues and describe the user-visible problem or risk.
2. Keep changes small and preserve the local-first and fail-closed audio-routing principles.
3. Do not add credentials, audio recordings, transcripts, endpoint IDs, or model files to the
   repository.

## Work-order record

Before implementation, record the owning product/capability and source-of-truth path,
acceptance criteria, delivery authority, dependencies, and evidence route. Follow the
[adoption baseline](docs/sdlc/adoption-plan.md), binding
[Definition of Done](docs/sdlc/definition-of-done.md), and
[Native Windows Evidence Profile](docs/sdlc/native-windows-evidence-profile.md).
Canonical factory guidance is consumed from the current `app-shared` source named in
the adoption baseline. Canonical product and capability artefacts (specifications, work
items, the integration contract) live in
[`app-shared/docs/products/lianiq/`](https://github.com/boris-heuer/app-shared/tree/main/docs/products/lianiq);
do not invent local catalog/configuration substitutes.

For every applicable acceptance criterion, retain the reviewed tree and exact
commit/build identity, local-check result, independent review, required CI, and real
user/operator evidence. Scope-based `N/A` needs its concrete reason; unavailable
required evidence is an open gap. Artifact completion or code verification never
alone claims runtime SystemOK.

## Development checks

Use Python 3.12. `scripts/setup.ps1` installs the hash-locked Windows dependency set from
`requirements-lock.txt` and then installs the project without resolving additional dependencies.
After it has created `.venv`, run:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe .\scripts\check_markdown_links.py
```

Add a failing deterministic test before changing behavior where practical. Hardware, virtual-cable,
and call-application checks are operator evidence; do not replace them with a simulated pass.

These checks run without a microphone or audio device:

```powershell
.\.venv\Scripts\python.exe .\scripts\doctor.py
.\.venv\Scripts\python.exe .\scripts\call_bridge_self_test.py --synthetic
```

The doctor never downloads anything; without provisioned models it lists each missing model and
exits with code 1. The synthetic Call Bridge self-test needs no models. After
`scripts/download_models.py` has provisioned the models, `scripts/self_test.py` runs both language
directions through the real models, and `scripts/ui_self_test.py` runs one German turn end to end
through the real window. After a visible UI
change, regenerate the README screenshot with `scripts/capture_readme_screenshot.py`; it uses
generic devices and a synthetic held turn, and loads no models. Commit the image as a 32-colour
palette PNG (for example Pillow `quantize(colors=32, method=Image.Quantize.FASTOCTREE,
dither=Image.Dither.NONE)`, saved with `optimize=True`) so it stays below the 32 KiB per-file
publishing limit.

## Languages, settings, and voices

- Languages are identified by BCP 47 language IDs from the built-in registry in
  `lianiq/languages/registry.py`. Do not hard-code language IDs, direction keys, or labels
  elsewhere in `lianiq/`; `tests/test_no_hardcoded_languages.py` fails on them. A language is
  selectable only when it is qualified in the registry; adding one is a capability change that
  starts in the canonical specification, not here.
- Settings use schema v2 (`"schema_version": 2`). A settings change updates `lianiq/config.py`,
  `config/settings.json`, and, when a v1 value maps to it, `lianiq/config_migration.py` with a
  migration test. Migration must stay lossless and must fail without writing when a value cannot
  be mapped.
- Translation models are configured per directed edge (`"<source>><target>"`); never derive a
  reverse edge. Voices are configured per language ID in `tts.voices`, and `tts.engines` selects
  Piper or sherpa-onnx per language.
- A new or changed model is pinned in `scripts/download_models.py` (revision or archive size and
  SHA-256), recorded in `models/model-manifest.json` by that script, and listed with its licence in
  [MODEL_LICENSES.md](MODEL_LICENSES.md).

## Pull requests

CI runs `pip check`, ruff, the Markdown link check, pytest, and a wheel build with a package
smoke test on Windows with Python 3.12. Explain the problem, the safety/privacy impact, and the
checks run. Update user documentation when commands, configuration, routing, or limitations
change. Keep downloaded models out of the change
unless explicitly requested.

Use the root [agent instructions](AGENTS.md) for the fresh-session owner,
evidence route, and publishing route (Factory SCM Gateway only, with its 32 KiB per-file write
limit). Questions and decisions return to the originating parent/operator
chat. Use GPT-5.6 Terra with medium reasoning and only the minimum necessary
independent review.

When changing a dependency, update `pyproject.toml`, regenerate `requirements-lock.txt` with the
documented `uv pip compile` command at the top of that file, and include both changes in the pull
request.

## Call Bridge changes

The Call Bridge is experimental. Preserve explicit endpoint selection, fixed lane direction, and
no-default-device fallback. Claims of compatibility or SystemOK require reproducible evidence from
the packaged application and the operator checklist; source tests alone are insufficient.

## Conduct and security

Follow the [Code of Conduct](CODE_OF_CONDUCT.md). Report suspected vulnerabilities privately as
described in [SECURITY.md], not in a public issue.
