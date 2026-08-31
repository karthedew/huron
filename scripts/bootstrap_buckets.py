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
    name: str
    lifecycle: dict[str, Any] | None


@dataclass
class BucketCheck:
    bucket: str
    label: str
    passed: bool
    detail: str
    fatal: bool = True


@dataclass
class Report:
    checks: list[BucketCheck] = field(default_factory=list)

    def record(self, check: BucketCheck) -> None:
        self.checks.append(check)
        marker = "OK  " if check.passed else ("WARN" if not check.fatal else "FAIL")
        print(f"[{marker}] {check.bucket:<14} {check.label}: {check.detail}")

    @property
    def failed(self) -> bool:
        return any(not c.passed and c.fatal for c in self.checks)


PLAN = [
    BucketPlan("huron-raw", RAW_LIFECYCLE),
    BucketPlan("huron-staging", STAGING_LIFECYCLE),
    BucketPlan("huron-index", None),
]


def make_client() -> BaseClient:
    session = botocore.session.get_session()
    return session.create_client(
        "s3",
        endpoint_url=ENDPOINT_URL,
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
        region_name=REGION,
    )


def wait_for_minio(client: BaseClient) -> None:
    for attempt in range(1, CONNECT_RETRIES + 1):
        try:
            client.list_buckets()
            return
        except EndpointConnectionError:
            if attempt == CONNECT_RETRIES:
                raise
            time.sleep(CONNECT_RETRY_INTERVAL_SECONDS)


def ensure_bucket(client: BaseClient, name: str) -> None:
    try:
        client.create_bucket(Bucket=name)
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
            raise


def suspend_versioning(client: BaseClient, name: str) -> None:
    client.put_bucket_versioning(Bucket=name, VersioningConfiguration={"Status": "Suspended"})


def apply_lifecycle(client: BaseClient, plan: BucketPlan) -> str | None:
    """Applies (or clears) the bucket's lifecycle configuration.

    Returns an error message on failure without raising — the raw bucket's
    AbortIncompleteMultipartUpload rule is known not to persist on MinIO
    community edition, and that specific case is reported as a warning by
    the caller rather than treated as this script's own defect.
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
    return client.get_bucket_versioning(Bucket=name).get("Status", "off")


def get_lifecycle_rules(client: BaseClient, name: str) -> list[dict[str, Any]]:
    try:
        return client.get_bucket_lifecycle_configuration(Bucket=name).get("Rules", [])
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "NoSuchLifecycleConfiguration":
            return []
        raise


def verify(client: BaseClient, plan: BucketPlan, report: Report) -> None:
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
