"""Shared packages: the coding logic, decoupled.

Every subpackage here is independent of every other one. A package that needs
another's capability declares a Protocol describing what it needs and receives
a conforming object from a service; it does not import the sibling that
provides it. Packages may import `huron.schema` and third-party libraries.

Enforced by the `Packages are independent of one another` import-linter
contract, not by convention.
"""
