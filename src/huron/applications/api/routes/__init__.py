"""HTTP routes and shared request helpers.

``v1`` exposes the legacy resource API at ``/api/v1``. ``preconditions`` provides
idempotency and optimistic-concurrency headers, and ``pagination`` provides page
envelopes and keyset cursors. Route packages own HTTP parsing and serialization;
domain operations enforce authorization and domain rules.
"""
