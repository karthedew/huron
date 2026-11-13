"""The marker of the tests that run a POSIX shell."""

import shutil

import pytest

#: Skips a test that runs ``sh`` on a machine without a POSIX shell.
NEEDS_SHELL = pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX shell")
