"""Domain objects and infrastructure capabilities.

Auth, catalog, RBAC and rawstore are independent siblings. Metastore adapters
consume domain types without depending on core or applications. Domain packages
never import their adapters. Consumer-owned protocols and constructor injection
connect capabilities; import-linter enforces the dependency direction.
"""
