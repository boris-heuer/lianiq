# Target UI preview verification

Date: 2026-10-08. Scope: standalone HTML/CSS/JavaScript design preview only.

## Performed

- Opened the locally served preview in the Codex in-app browser.
- Exercised all eleven Scenario options at a 1280x960 CSS viewport: each rendered one
  primary heading with no horizontal document overflow.
- Checked Conversation, Call Bridge, Language packs and Settings at 850x560 and 640x800:
  no horizontal document overflow in those eight combinations. Vertical scrolling remains
  available. This does not establish native Windows DPI or screen-reader compliance.
- Selected all four synthetic endpoints, completed both simulated route confirmations and
  confirmed Start Call Bridge became enabled. Confirmed the active bridge locked language
  selection. No real audio or device was accessed.
- Selected English/Spanish: text-conversation start was enabled; replay of the Spanish
  translation was disabled because the example voice is absent.
- Stopped the English/Spanish conversation and confirmed both turns were preserved.
- Selected English/French and confirmed start was blocked by missing pair capability.
- Inspected desktop renders and saved seven complete screenshots under `screenshots/`.
- Browser developer error log was empty after scenario/interaction checks.
- `node --check docs/ui/target/preview.js` passed.

## Repository checks

The repository Markdown-link checker and staged whitespace check passed before publishing
this package. No application Python behavior or dependencies are modified, so native model,
audio and full application tests are outside this artifact-only change.

## Limits

Audio tests, clipboard availability, file dialogs, pack provisioning, native accessibility,
translation quality and real call behavior are not validated by these previews. The sample
1.8-second processing label is illustrative, not a benchmark. Project membership was not
modified because GitHub Project discovery lacked `read:project` access.

The proposed design remains subject to operator review and implementation acceptance under
[#20](https://github.com/boris-heuer/lianiq/issues/20), particularly
[#32](https://github.com/boris-heuer/lianiq/issues/32). Mockup approval must not close the
implementation issues.
