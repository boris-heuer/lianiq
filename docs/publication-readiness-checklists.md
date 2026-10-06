# Publication Readiness Checklists

These checklists define the evidence required for the source repository to be public and clonable.
They do not promote the experimental Call Bridge to production `SystemOK`; its real-device and
real-call gates remain separately documented in
[`call-bridge-system-ok.md`](call-bridge-system-ok.md).

## Phase 1 — durable legal and clone baseline

- [x] GPL-3.0-or-later project license and package metadata are present.
- [x] Third-party package/model notices and Mandarin bring-your-own licensing boundary are present.
- [x] Model downloads use immutable revisions and emit a SHA-256 manifest.
- [x] Safe tracked defaults contain no machine-specific endpoint identities.
- [x] Runtime endpoint identities are written only to ignored `config/settings.local.json`.
- [x] Python 3.12 Windows dependencies are hash-locked in `requirements-lock.txt`.
- [x] The complete tree is committed and pushed to GitHub.
- [x] A fresh clone from GitHub installs, tests, builds a wheel and Windows application, imports the
      wheel, and starts the packaged application without reusing the source workspace.

## Phase 2 — technical publication readiness

- [x] CI has least-privilege permissions, immutable action SHAs, lint, tests, dependency checks,
      wheel build, and installed-wheel smoke test.
- [x] CodeQL and weekly Dependabot configuration are present.
- [x] Thin builds exclude model weights by default; model inclusion is explicit and manifest-bound.
- [x] Call Bridge is disabled by default, uses explicit stable endpoint identities, and fails closed.
- [x] Automated evidence distinguishes mechanism checks from hardware/application acceptance.
- [ ] Branch protection/rules, vulnerability reporting, dependency alerts, and secret scanning are
      enabled on the public GitHub repository.
- [ ] Required GitHub CI and CodeQL checks pass on the exact merge candidate.

## Phase 3 — stars and competency evidence

- [x] README states the problem, limits, reference architecture, setup, testing, and safety boundary.
- [x] Engineering case study and AI-assisted-development disclosure explain decisions and evidence.
- [x] Contribution, conduct, security, support, roadmap, changelog, and citation files are present.
- [x] Issue and pull-request templates are present.
- [x] A purpose-built social-preview asset is versioned under `docs/assets/`.
- [ ] Repository description, topics, social preview, and public visibility are configured on GitHub.
- [ ] Initial contributor-friendly issues are published and labelled.
- [ ] A source-only `v0.1.0` release is published; no unsigned binary or unreviewed model is attached.

## External launch gate

Publication is complete only when all unchecked rows above have evidence from the remote repository.
The Call Bridge may remain experimental after source publication. It becomes production `SystemOK`
only after every packaged two-cable, disconnect/reconnect, latency, and real WeChat call row in the
operator checklist has passed on the target Windows system.
