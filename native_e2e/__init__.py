"""Native Windows end-to-end evidence tooling for Lianiq (CAP-0174).

Test tooling, not part of the ``lianiq`` package: the wheel includes only ``lianiq*`` and
the default ``pytest`` collects only ``tests/``. ``native_e2e.evidence`` and
``native_e2e.ssim`` are portable and unit-tested in normal CI; the row runner that drives
the real window runs only on the dedicated Windows 11 VM.
"""
