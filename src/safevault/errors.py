class SafeVaultError(Exception):
    """Base class for expected SafeVault user-facing errors."""


class RootNotFoundError(SafeVaultError):
    """Raised when a path is not under a protected root."""


class FileNotTrackedError(SafeVaultError):
    """Raised when a file has no tracked SafeVault history."""


class ObjectMissingError(SafeVaultError):
    """Raised when a referenced object is absent from the object store."""


class ObjectCorruptError(SafeVaultError):
    """Raised when a content object does not match its BLAKE3 address."""


class InvalidDurationError(SafeVaultError):
    """Raised when a duration value cannot be parsed."""


class SandboxNotFoundError(SafeVaultError):
    """Raised when a sandbox id is unknown."""


class UnsafeOperationError(SafeVaultError):
    """Raised when an operation would violate a safety rule."""
