"""Services: the runnable processes.

One subpackage per deployable in design/architecture.html section 2, plus the
operator CLI. A service is where objects get instantiated and wired: it reads
settings, constructs the concrete stores, and injects them into the packages
that declare Protocols for them.

Services are independent of one another. Logic that two services would share
belongs in a package, not in a sibling import.
"""
