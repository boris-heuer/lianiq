## Summary

Describe the user problem and the change.

## Evidence

- [ ] `python -m pytest`
- [ ] `python -m ruff check .`
- [ ] Documentation/configuration updated where needed
- [ ] Not run (explain below)

## SDLC record

- [ ] Work order/issue, owner, source-of-truth path, acceptance criteria, delivery authority, and dependencies are identified
- [ ] Each applicable acceptance criterion maps to the exact reviewed commit/build and verification result
- [ ] Applicable local checks, independent exact-tree review, and required CI are recorded
- [ ] Real user/operator evidence is recorded, or a concrete scope-based `N/A` reason is given
- [ ] Remaining gaps include cause, impact, responsible actor, and exact unblock action
- [ ] Artifact completion, code verification, and runtime SystemOK are reported separately; this PR does not claim runtime SystemOK without the required profile evidence

Follow the [binding Definition of Done](https://github.com/boris-heuer/lianiq/blob/main/docs/sdlc/definition-of-done.md), [native Windows evidence profile](https://github.com/boris-heuer/lianiq/blob/main/docs/sdlc/native-windows-evidence-profile.md), and [current canonical factory ownership guidance](https://github.com/boris-heuer/app-shared/blob/main/repo-config/skills/implement-capability/references/repo-ownership-routing.md). Canonical registration remains pending [#40](https://github.com/boris-heuer/lianiq/issues/40); this template does not authorize a local substitute.

## Safety and privacy

- [ ] No credentials, recordings, transcripts, endpoint IDs, or downloaded models added
- [ ] Call Bridge changes preserve explicit endpoints and fail-closed behavior
- [ ] Hardware/call compatibility claims are backed by documented operator evidence

## Notes

List any remaining operator gate, limitation, or follow-up.
