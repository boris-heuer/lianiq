"""Offline language provisioning: pack catalog, pack file, manifest and pack states (CAP-0171).

See ``docs/products/lianiq/capabilities/offline-language-provisioning/contract.md`` in
``boris-heuer/app-shared``. Every module of this package is Qt-free.

The package re-exports nothing on purpose: ``lianiq.languages.capabilities`` imports
``lianiq.packs.verify``, and an eager import of ``catalog`` here (which imports
``lianiq.languages``) would make that a circular import. Import from the submodules.
"""
