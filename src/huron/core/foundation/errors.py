"""Shared stable failures independent of any Huron domain or adapter."""

from __future__ import annotations

from typing import ClassVar


class DomainError(Exception):
    """A failure whose stable code is part of Huron's public contract.

    A subclass declares its ``code`` and ``status_code``. It may also declare
    ``retry_after``, the number of seconds a client should wait before
    repeating the refused request; None, the default, asks for no wait.
    """

    code: str
    status_code: ClassVar[int]
    retry_after: ClassVar[int | None] = None

    def __init__(self, detail: str | None = None, *, context: dict[str, object] | None = None):
        """Record the human-readable detail and structured context.

        Args:
            detail: The message; defaults to the lower-case code with spaces.
            context: Additional public failure facts.

        Raises:
            TypeError: If the abstract base is instantiated directly.
        """
        if type(self) is DomainError:
            raise TypeError("DomainError is abstract; raise a subclass with a stable code")
        self.detail = detail or self.code.replace("_", " ").lower()
        self.context = context or {}
        super().__init__(self.detail)

    def as_problem(self) -> dict[str, object]:
        """Return the stable RFC 9457-style failure representation.

        Returns:
            The problem fields, including context only when nonempty.
        """
        return {
            "type": f"urn:huron:error:{self.code.lower()}",
            "title": self.code.replace("_", " ").title(),
            "status": self.status_code,
            "code": self.code,
            "detail": self.detail,
            **({"context": self.context} if self.context else {}),
        }


class IdempotencyKeyReused(DomainError):
    """The same retry key was replayed with a different request."""

    code, status_code = "IDEMPOTENCY_KEY_REUSED", 409


class PreconditionFailed(DomainError):
    """The supplied version is invalid or the resource has advanced."""

    code, status_code = "PRECONDITION_FAILED", 412


class ResourceNotFound(DomainError):
    """The named resource is absent or undiscoverable."""

    code, status_code = "NOT_FOUND", 404


class Forbidden(DomainError):
    """The caller is authenticated, but its authority does not allow this.

    Raised once the principal is known, so it is always a 403 and never a
    401: the credential was fine, the authority was not. Every source of
    authority refuses this way - role bindings, the permissions a delegated
    request carries, ownership of the addressed resource - and so does an
    account whose standing no longer allows the operation.
    """

    code, status_code = "FORBIDDEN", 403


class PathRuleViolation(DomainError):
    """A lexical path or storage-layout rule failed."""

    code = "PATH_RULE_VIOLATION"
    status_code = 400

    def __init__(self, code_or_detail: str, path: str | None = None):
        """Build a shared-code failure or a specific path-rule failure.

        Args:
            code_or_detail: Detail without a path, otherwise a specific error code.
            path: The offending path, when using a specific code.
        """
        if path is None:
            detail = code_or_detail
            self.code = type(self).code
        else:
            detail = f"{code_or_detail}: {path!r}"
            self.code = code_or_detail
        super().__init__(detail, context={"path": path} if path is not None else None)


class AuthError(Exception):
    """A credential could not be resolved to a principal.

    The base of every authentication failure and the ``INVALID_CREDENTIAL``
    condition in its own right: a malformed token, an unknown key or
    session id, a secret that does not match, a signature or claim the
    verifier rejects, or no credential at all. A resolver raises it
    directly whenever nothing more specific is true, and the message is
    the only place it says which of those cases applied. It is not a
    ``DomainError``: every authentication failure answers 401 together
    with a challenge naming the scheme the service accepts.
    """

    code = "INVALID_CREDENTIAL"


ERROR_CODES = frozenset(
    {
        "IDEMPOTENCY_KEY_REUSED",
        "PRECONDITION_FAILED",
        "NOT_FOUND",
        "FORBIDDEN",
        "PATH_RULE_VIOLATION",
        "INVALID_CREDENTIAL",
    }
)
