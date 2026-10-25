"""Runnable application entry points and composition roots.

The ``api`` application loads settings, constructs adapters, binds authenticated
actors to core services, and manages process lifetimes. Shared workflows and
domain rules belong in core. Applications do not import one another.
"""
