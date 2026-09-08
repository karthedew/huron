"""The v1 endpoint modules, one per resource.

Each exposes ``router`` for its own path root and, for a resource addressed
from more than one root, an additional router named for the parent it hangs
under (``organization_projects``, ``project_datasets``, and so on).
"""
