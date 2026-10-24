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

Canonical capability registration remains blocked until SDLC-03 ([#40](https://github.com/boris-heuer/lianiq/issues/40)) resolves its factory consumer-admission dependency. Do not create a local catalog, capability folder, or `factory.config` as a workaround. Artifact-only adoption work owned by [#37](https://github.com/boris-heuer/lianiq/issues/37) may use its issue and the adoption baseline; runtime feature dispatch under [#20](https://github.com/boris-heuer/lianiq/issues/20) waits for coherent canonical owner/spec mapping.

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

## Fresh-session walkthrough

From this file, open the assigned issue, then the adoption baseline and Definition
of Done. Resolve canonical ownership at the linked current `app-shared` guidance;
then follow the issue's evidence route. The pull-request template repeats the
required evidence record. This guidance does not authorize hooks, MCP, credentials,
system configuration, or runtime changes.
