# Lianiq Agent Instructions

Lianiq is an independent Python/PySide6 Windows product. It adopts the Software
Factory delivery lifecycle without adopting an app-platform, .NET, or Blazor runtime
stack.

## Start here

1. Read [CONTRIBUTING.md](CONTRIBUTING.md), the
   [adoption baseline](docs/sdlc/adoption-plan.md), the binding
   [Definition of Done](docs/sdlc/definition-of-done.md), and the
   [Native Windows Evidence Profile](docs/sdlc/native-windows-evidence-profile.md).
2. Read the assigned issue and record its owner, source-of-truth path, acceptance
   criteria, delivery authority, dependencies, and evidence route before editing.
3. Use current canonical factory guidance by pointer from
   [`boris-heuer/app-shared`](https://github.com/boris-heuer/app-shared):
   [`repo-ownership-routing.md`](https://github.com/boris-heuer/app-shared/blob/main/repo-config/skills/implement-capability/references/repo-ownership-routing.md)
   and
   [`coordination.md`](https://github.com/boris-heuer/app-shared/blob/main/.claude/rules/coordination.md).
   Do not copy or modify factory policy in this repository.
4. Follow the current canonical
   [`agent operating mode`](https://github.com/boris-heuer/app-shared/blob/main/docs/agent-operating-mode.md)
   and [PR workflow](https://github.com/boris-heuer/app-shared/blob/main/repo-config/dev-guides/pr-workflow.md)
   for review, CI, merge, and completion evidence.

Lianiq is registered as a factory product (SDLC-03,
[#40](https://github.com/boris-heuer/lianiq/issues/40), closed). Canonical product and
capability artefacts — `product.md`, the product capability model, the integration
contract, and one folder per capability (for example `language-pair-contract`, CAP-0169) —
live in
[`app-shared/docs/products/lianiq/`](https://github.com/boris-heuer/app-shared/tree/main/docs/products/lianiq).
Specifications, work items, and contract changes are made there, not in this repository.
Do not create a local catalog, capability folder, or `factory.config`. This repository
owns the runtime source, tests, user documentation, and app-specific evidence.

## Code map

- `lianiq/languages/`: the built-in language registry (BCP 47 language IDs, qualified and
  planned languages), language pairs, directed capabilities, usage-mode requirements, and
  readiness. Language IDs and edge keys are not hard-coded elsewhere in `lianiq/`;
  `tests/test_no_hardcoded_languages.py` enforces this and its docstring lists the few
  permitted exceptions.
- `lianiq/config.py` and `lianiq/config_migration.py`: settings schema v2 (`languages`,
  `translation.edges`, `tts.voices`, `tts.engines`) and the lossless v1 migration.
- `lianiq/conversation/routing.py`: pair-scoped turn routing and held turns.
- `lianiq/stt/`, `lianiq/translation/`, `lianiq/tts/`: Faster-Whisper, MarianMT per
  directed edge, and voices per language (Piper, sherpa-onnx, selected by `voice_router`).
- `lianiq/call_bridge/` and `lianiq/audio/`: the experimental Call Bridge and audio I/O.
- `lianiq/ui/`: the PySide6 window (`main_window.py`) composing the workspaces in
  `lianiq/ui/workspaces/` (Conversation, Call Bridge), the result panels and the held-turn
  bar; each widget sets its own accessible name. `tests/test_ui_module_sizes.py` keeps
  every file under `lianiq/ui/` at most 32 KiB.
- `scripts/download_models.py` and `models/model-manifest.json`: pinned model provisioning;
  record model licences in [MODEL_LICENSES.md](MODEL_LICENSES.md).

## Delivery rules

- Use GPT-5.6 Terra with medium reasoning. Do not use priority execution or default
  fan-out; use only the minimum necessary independent reviewer.
- Keep repository and GitHub prose in English. Multilingual translation inputs,
  expected outputs, speech samples, and native language names are functional data.
- Preserve local/offline privacy and fail-closed audio routing. The experimental Call
  Bridge requires its profile-specific packaged and operator evidence; tests and
  mockups alone do not establish runtime SystemOK.
- Keep the exact reviewed tree, commit/build identity, applicable local checks,
  independent review, CI, and user/operator evidence traceable to each acceptance
  criterion. Use a concrete scope-based `N/A` only where permitted by the Definition
  of Done; missing required evidence leaves the work open.
- Route every question or decision to the originating parent/operator chat. Do not
  redirect it to a separate agent chat.
- Publish branches, commits, pull requests, and merges only through the Factory SCM
  Gateway (squash auto-merge pinned to the reviewed head). Do not use `git push`, the
  `gh` CLI, another GitHub integration, or a direct merge. The Gateway writes at most
  32 KiB (decoded) per file; a larger file needs explicit operator approval for that
  file. On an unknown outcome, read the state back
  before acting; never retry automatically.
- Before the first commit, an independent reviewer reviews the frozen staged tree; record
  the review receipt as the PR workflow requires.

## Fresh-session walkthrough

From this file, open the assigned issue or canonical work item, then the adoption
baseline and Definition of Done. Resolve canonical ownership at the linked current
`app-shared` guidance and the product folder above; then follow the evidence route.
The development commands are in [CONTRIBUTING.md](CONTRIBUTING.md#development-checks).
The pull-request template repeats the required evidence record. This guidance does not
authorize hooks, MCP, credentials, system configuration, or runtime changes.
