"""Real getfacl/setfacl round trips; skipped where the filesystem or tools lack ACL support."""

import grp
import os
from pathlib import Path

import pytest

from huron.pkg.fs.acl import Acl, AclEntry, SubprocessRunner, acl_supported, read_acl, write_acl

pytestmark = pytest.mark.acl


@pytest.fixture
def directory(tmp_path: Path) -> Path:
    if not acl_supported(tmp_path, SubprocessRunner()):
        pytest.skip("getfacl is not installed or the filesystem has no ACL support")
    return tmp_path


def test_written_acl_reads_back(directory: Path) -> None:
    group = grp.getgrgid(os.getgid()).gr_name
    base = {
        AclEntry("user", None, "rwx"),
        AclEntry("group", None, "r-x"),
        AclEntry("other", None, "---"),
        AclEntry("mask", None, "rwx"),
    }
    acl = Acl(
        frozenset(base | {AclEntry("group", group, "rwx")}),
        frozenset(base | {AclEntry("group", group, "r-x")}),
    )
    runner = SubprocessRunner()
    write_acl(directory, acl, runner)
    assert read_acl(directory, runner).without_masks() == acl.without_masks()
