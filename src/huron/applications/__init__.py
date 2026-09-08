"""Runnable application entry points and composition roots.

Applications load settings, construct adapters, bind authenticated actors to core
services, and manage process lifetimes. Shared workflows belong in core; domain
rules and capability implementations belong in pkg. Entry points do not import
one another.
"""
