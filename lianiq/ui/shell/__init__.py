"""The desktop shell: workspace registry, navigation, active-session owner (CAP-0168).

``workspaces`` and ``session_owner`` are Qt-free; ``navigation`` and ``session_strip`` are
the PySide6 widgets over them. This package module imports nothing, so importing a Qt-free
module never loads PySide6.
"""
