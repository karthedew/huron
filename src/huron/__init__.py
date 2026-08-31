"""Huron: a raw-data-first lakehouse control plane for scientific projects.

Three top-level surfaces, and the dependency rule between them runs one way:

    service/  runnable processes. Composition roots: they construct concrete
              objects, inject them into packages, and hold all the glue.
    pkg/      shared libraries. Each is independent of every other -- a package
              never imports a sibling. Where one needs another's capability it
              declares a Protocol and takes an implementation by injection.
    schema/   contracts shared across services. The one thing anything may
              import.

service -> pkg -> schema. Never the reverse, and never sideways.
"""
