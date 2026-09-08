"""Shared storage failure contracts."""


class PartLengthMismatchError(ValueError):
    """The stream delivered a different number of bytes than the part was planned to hold."""
