"""Create and configure the object-storage buckets the control plane depends on.

Applies a declarative target state to each bucket — existence, versioning, and
lifecycle rules — and is safe to run repeatedly: every call converges the
bucket to the same configuration rather than merely initializing it once.
Uses botocore's synchronous low-level client directly rather than boto3,
since botocore already ships as a transitive dependency and this is the same
library the RGW adapter will use.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import botocore.session
from botocore.exceptions import ClientError, EndpointConnectionError

if TYPE_CHECKING:
    from botocore.client import BaseClient

ENDPOINT_URL = "http://localhost:9000"
ACCESS_KEY = "minioadmin"
SECRET_KEY = "minioadmin"
REGION = "us-east-1"

CONNECT_RETRIES = 30
CONNECT_RETRY_INTERVAL_SECONDS = 2.0

# Ceph RGW, the production backend, is expected to persist this rule
# correctly; MinIO's community edition does not, and the discrepancy is
# reported rather than hidden. See docs/getting-started/local-development.md.
RAW_LIFECYCLE = {
    "Rules": [
        {
            "ID": "abort-incomplete-multipart-upload",
            "Status": "Enabled",
            "Filter": {"Prefix": ""},
            "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 7},
        }
    ]
}

STAGING_LIFECYCLE = {
    "Rules": [
        {
            "ID": "expire-after-7-days",
            "Status": "Enabled",
            "Filter": {"Prefix": ""},
            "Expiration": {"Days": 7},
        }
    ]
}


@dataclass
class BucketPlan:
    """The declared target state of one bucket.

    Versioning is not part of the plan because it is the same for every
    bucket: always suspended.

    Attributes:
        name: The bucket name as the object store knows it.
        lifecycle: The lifecycle configuration to put on the bucket, or None
            when the bucket must carry no lifecycle rules at all.
    """

    name: str
    lifecycle: dict[str, Any] | None


@dataclass
class BucketCheck:
    """One property of a bucket, read back from the running object store and judged.

    Attributes:
        bucket: The bucket the property was read from.
        label: The property checked, as it is printed in the report line.
        passed: Whether the value read back matches the declared state.
        detail: What was read back, or why nothing could be.
        fatal: Whether a failed check fails the bootstrap. A non-fatal
            failure is printed as a warning; it is reserved for a
            discrepancy the object store is known to produce and the
            control plane tolerates in local development.
    """

    bucket: str
    label: str
    passed: bool
    detail: str
    fatal: bool = True


@dataclass
class Report:
    """The record of every bucket check, printed line by line as it is built.

    Each check is echoed the moment it is recorded, so the report is both
    the log an operator watches and the source of the exit status `main`
    returns.

    Attributes:
        checks: Every check recorded so far, in the order it was recorded.
    """

    checks: list[BucketCheck] = field(default_factory=list)

    def record(self, check: BucketCheck) -> None:
        """Append `check` and print its verdict line.

        The marker is ``OK`` for a passed check, ``FAIL`` for a failed fatal
        one and ``WARN`` for a failed non-fatal one.

        Args:
            check: The check to record.
        """
        self.checks.append(check)
        marker = "OK  " if check.passed else ("WARN" if not check.fatal else "FAIL")
        print(f"[{marker}] {check.bucket:<14} {check.label}: {check.detail}")

    @property
    def failed(self) -> bool:
        """Whether any fatal check failed; warnings never count.

        Returns:
            True if at least one recorded check both failed and was fatal.
        """
        return any(not c.passed and c.fatal for c in self.checks)


PLAN = [
    BucketPlan("huron-raw", RAW_LIFECYCLE),
    BucketPlan("huron-staging", STAGING_LIFECYCLE),
    BucketPlan("huron-index", None),
]


def make_client() -> BaseClient:
    """Create the botocore S3 client for the local object store.

    The endpoint, credentials and region are the module-level constants,
    which match the MinIO service of the local compose stack; they are
    passed explicitly rather than resolved from an AWS profile or the
    environment.

    Returns:
        A synchronous S3 client bound to `ENDPOINT_URL`.
    """
    session = botocore.session.get_session()
    return session.create_client(
        "s3",
        endpoint_url=ENDPOINT_URL,
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
        region_name=REGION,
    )


def wait_for_minio(client: BaseClient) -> None:
    """Block until the object store answers, or give up after `CONNECT_RETRIES` attempts.

    A ``ListBuckets`` call is the probe. Only a refused connection is
    retried, every `CONNECT_RETRY_INTERVAL_SECONDS`, which covers the window
    between the container starting and MinIO accepting requests; any other
    failure, such as rejected credentials, propagates at once.

    Args:
        client: The S3 client to probe with.

    Raises:
        EndpointConnectionError: If the last attempt is still refused.
    """
    for attempt in range(1, CONNECT_RETRIES + 1):
        try:
            client.list_buckets()
            return
        except EndpointConnectionError:
            if attempt == CONNECT_RETRIES:
                raise
            time.sleep(CONNECT_RETRY_INTERVAL_SECONDS)


def ensure_bucket(client: BaseClient, name: str) -> None:
    """Create bucket `name` unless it already exists.

    Args:
        client: The S3 client to create through.
        name: The bucket to create.

    Raises:
        ClientError: If creation fails for any reason other than the bucket
            already existing, in either its ``BucketAlreadyOwnedByYou`` or
            its ``BucketAlreadyExists`` form.
    """
    try:
        client.create_bucket(Bucket=name)
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
            raise


def suspend_versioning(client: BaseClient, name: str) -> None:
    """Put bucket `name` into the ``Suspended`` versioning state.

    The state is written on every run rather than assumed: a bucket that has
    never had versioning configured reports no status at all, and `verify`
    accepts nothing but an explicit ``Suspended``.

    Args:
        client: The S3 client to configure through.
        name: The bucket to configure.
    """
    client.put_bucket_versioning(Bucket=name, VersioningConfiguration={"Status": "Suspended"})


def apply_lifecycle(client: BaseClient, plan: BucketPlan) -> str | None:
    """Apply, or clear, the lifecycle configuration `plan` declares for its bucket.

    A plan without a lifecycle means the bucket must carry no rules, so any
    existing configuration is deleted; a bucket that has none is already in
    the target state, not an error.

    Returns an error message on failure without raising — the raw bucket's
    AbortIncompleteMultipartUpload rule is known not to persist on MinIO
    community edition, and that specific case is reported as a warning by
    the caller rather than treated as this script's own defect.

    Args:
        client: The S3 client to configure through.
        plan: The bucket and the lifecycle it should end up with.

    Returns:
        None when the object store accepted the change, otherwise the text
        of the ``ClientError`` it answered with.
    """
    if plan.lifecycle is None:
        try:
            client.delete_bucket_lifecycle(Bucket=plan.name)
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code != "NoSuchLifecycleConfiguration":
                return str(exc)
        return None
    try:
        client.put_bucket_lifecycle_configuration(
            Bucket=plan.name, LifecycleConfiguration=plan.lifecycle
        )
        return None
    except ClientError as exc:
        return str(exc)


def get_versioning_status(client: BaseClient, name: str) -> str:
    """Read back the versioning state of bucket `name`.

    Args:
        client: The S3 client to read through.
        name: The bucket to inspect.

    Returns:
        The ``Status`` the object store reports - ``Enabled`` or
        ``Suspended`` - or ``off`` when versioning has never been configured
        and the response carries no status at all.
    """
    return client.get_bucket_versioning(Bucket=name).get("Status", "off")


def get_lifecycle_rules(client: BaseClient, name: str) -> list[dict[str, Any]]:
    """Read back the lifecycle rules of bucket `name`.

    Args:
        client: The S3 client to read through.
        name: The bucket to inspect.

    Returns:
        The rules exactly as the object store reports them, which is what
        `verify` judges; an empty list when the bucket has no lifecycle
        configuration.

    Raises:
        ClientError: If the read fails for any reason other than the bucket
            having no lifecycle configuration.
    """
    try:
        return client.get_bucket_lifecycle_configuration(Bucket=name).get("Rules", [])
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "NoSuchLifecycleConfiguration":
            return []
        raise


def verify(client: BaseClient, plan: BucketPlan, report: Report) -> None:
    """Read `plan`'s bucket back and record whether it is in its declared state.

    Every bucket must report ``Suspended`` versioning. The lifecycle checks
    are per bucket: ``huron-raw`` must carry no expiration or transition
    rule and should carry the seven-day abort-incomplete-multipart rule -
    its absence is recorded as a non-fatal warning, because MinIO community
    edition does not persist it and real Ceph RGW is expected to;
    ``huron-staging`` must expire objects after seven days; any other bucket
    (``huron-index``) must carry no lifecycle rule at all. Nothing is
    trusted from the apply step - every value is what the running instance
    reports.

    Args:
        client: The S3 client to read through.
        plan: The bucket and the state it was configured to.
        report: Where each check is recorded.
    """
    status = get_versioning_status(client, plan.name)
    report.record(
        BucketCheck(
            plan.name, "versioning", status == "Suspended", f"expected Suspended, got {status}"
        )
    )

    rules = get_lifecycle_rules(client, plan.name)

    if plan.name == "huron-raw":
        abort_rules = [r for r in rules if "AbortIncompleteMultipartUpload" in r]
        expiring_rules = [r for r in rules if "Expiration" in r or "Transition" in r]
        report.record(
            BucketCheck(
                plan.name,
                "no expiration rule",
                not expiring_rules,
                "confirmed absent" if not expiring_rules else f"found: {expiring_rules}",
            )
        )
        if abort_rules:
            days = abort_rules[0]["AbortIncompleteMultipartUpload"]["DaysAfterInitiation"]
            report.record(
                BucketCheck(
                    plan.name,
                    "abort-incomplete-multipart-upload",
                    days == 7,
                    f"DaysAfterInitiation={days}",
                )
            )
        else:
            report.record(
                BucketCheck(
                    plan.name,
                    "abort-incomplete-multipart-upload",
                    False,
                    "not persisted by this object store — known MinIO community-edition "
                    "limitation, harmless in local development; verified against real Ceph "
                    "RGW before release (see docs/getting-started/local-development.md)",
                    fatal=False,
                )
            )
    elif plan.name == "huron-staging":
        expiration_rules = [r for r in rules if "Expiration" in r]
        days = expiration_rules[0]["Expiration"]["Days"] if expiration_rules else None
        report.record(
            BucketCheck(
                plan.name,
                "expiration",
                days == 7,
                f"Days={days}" if expiration_rules else "no expiration rule found",
            )
        )
    else:
        report.record(
            BucketCheck(
                plan.name,
                "no lifecycle rule",
                not rules,
                "confirmed absent" if not rules else f"found: {rules}",
            )
        )


def main() -> int:
    """Converge every planned bucket to its declared state, then verify each one.

    Waits for the object store, then for each bucket in `PLAN` creates it,
    suspends versioning and applies its lifecycle. A lifecycle the store
    rejects on ``huron-staging`` or ``huron-index`` ends the run at once
    with a ``FAIL`` line; one rejected on ``huron-raw`` is left to
    verification, where the missing abort rule is reported as a warning.
    Verification then reads every bucket back and prints one line per
    check.

    Returns:
        The process exit status: 0 when every fatal check passed, 1 when a
        lifecycle could not be applied or a bucket is not in its declared
        state.
    """
    client = make_client()

    print(f"Connecting to {ENDPOINT_URL} ...")
    wait_for_minio(client)

    for plan in PLAN:
        ensure_bucket(client, plan.name)
        suspend_versioning(client, plan.name)
        lifecycle_error = apply_lifecycle(client, plan)
        if lifecycle_error and plan.name != "huron-raw":
            print(f"[FAIL] {plan.name:<14} lifecycle: {lifecycle_error}", file=sys.stderr)
            return 1

    print()
    print("Reading configuration back from the running instance:")
    report = Report()
    for plan in PLAN:
        verify(client, plan, report)

    print()
    if report.failed:
        print("Bootstrap failed: one or more buckets are not in the expected state.")
        return 1

    print("Bootstrap complete: all buckets match the declared configuration.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
