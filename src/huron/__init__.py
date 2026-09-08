"""Huron: a scientific datalake with reusable authorized workflows.

Applications expose transports and construct adapters. Core coordinates authorized
operations. Domain packages own invariants; infrastructure packages implement I/O.
Schema provides shared document contracts. Dependencies point inward:
applications -> core -> pkg -> schema, with adapter imports at composition roots.
"""
