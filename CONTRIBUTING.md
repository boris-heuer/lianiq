# Contributing

Thanks for improving `lianiq`. Contributions are welcome through focused issues and pull
requests.

## Before changing code

1. Search open issues and describe the user-visible problem or risk.
2. Keep changes small and preserve the local-first and fail-closed audio-routing principles.
3. Do not add credentials, audio recordings, transcripts, endpoint IDs, or model files to the
   repository.

## Development checks

Use Python 3.12. `scripts/setup.ps1` installs the hash-locked Windows dependency set from
`requirements-lock.txt` and then installs the project without resolving additional dependencies.
After it has created `.venv`, run:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
```

Add a failing deterministic test before changing behavior where practical. Hardware, virtual-cable,
and call-application checks are operator evidence; do not replace them with a simulated pass.

## Pull requests

Explain the problem, the safety/privacy impact, and the checks run. Update user documentation when
commands, configuration, routing, or limitations change. Keep downloaded models out of the change
unless explicitly requested.

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
