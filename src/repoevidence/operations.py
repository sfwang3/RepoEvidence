"""Application-level operation seam for interactive and future presenters."""

from __future__ import annotations

import re
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, TypeVar

from repoevidence.application import (
    generate_report,
    inspect_repository,
    open_report,
    reconcile_repository,
    verify_mysql_repository,
)

_SENSITIVE_KEY = re.compile(
    r"(?:password|passwd|secret|token|api[_-]?key|private[_-]?key|credential|"
    r"connection[_-]?string|authorization|dsn)",
    re.IGNORECASE,
)
_SAFE_TYPES = (str, int, float, bool)
_SAFE_METADATA_KEYS = frozenset(
    {
        "path",
        "relative_path",
        "artifact",
        "phase",
        "phase_id",
        "elapsed_ms",
        "error_type",
        "count",
        "item_count",
    }
)
SafeValue = str | int | float | bool
T = TypeVar("T")


@dataclass(frozen=True)
class OperationEvent:
    """Presentation-neutral event; never part of the machine artifact contract."""

    operation_id: str
    operation_kind: str
    phase_id: str
    event_kind: str
    monotonic_timestamp: float
    safe_metadata: Mapping[str, SafeValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "safe_metadata", _safe_metadata(self.safe_metadata))


class OperationBusyError(RuntimeError):
    """Raised when an artifact-producing operation is already running."""


class OperationActionError(RuntimeError):
    """Raised for a stable action id that is not available in this service."""

    def __init__(self, action: str) -> None:
        self.action = action
        super().__init__(f"Action unavailable: {action}")


@dataclass(frozen=True)
class WorkspaceOperationResult:
    action: str
    value: object


OperationListener = Callable[[OperationEvent], None]
OperationCallable = Callable[[], T]


class OperationRunner:
    """Single-flight synchronous runner suitable for a UI-owned worker thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def execute(
        self,
        operation_kind: str,
        operation: OperationCallable[T],
        *,
        listener: OperationListener | None = None,
        phase_id: str = "execute",
    ) -> T:
        if not self._lock.acquire(blocking=False):
            raise OperationBusyError("An artifact-producing operation is already running.")
        operation_id = uuid.uuid4().hex
        started_at = time.monotonic()
        try:
            _emit(
                listener,
                operation_id=operation_id,
                operation_kind=operation_kind,
                phase_id=phase_id,
                event_kind="started",
            )
            result = operation()
            _emit(
                listener,
                operation_id=operation_id,
                operation_kind=operation_kind,
                phase_id=phase_id,
                event_kind="completed",
                safe_metadata={"elapsed_ms": round((time.monotonic() - started_at) * 1000)},
            )
            return result
        except Exception as error:
            _emit(
                listener,
                operation_id=operation_id,
                operation_kind=operation_kind,
                phase_id=phase_id,
                event_kind="failed",
                safe_metadata={
                    "error_type": type(error).__name__,
                    "elapsed_ms": round((time.monotonic() - started_at) * 1000),
                },
            )
            raise
        finally:
            self._lock.release()


class WorkspaceOperationService:
    """Dispatch stable action ids to existing application services."""

    def __init__(
        self,
        root: str,
        *,
        language: str = "en",
        runner: OperationRunner | None = None,
    ) -> None:
        self.root = root
        self.language = language
        self.runner = runner or OperationRunner()

    def execute(
        self,
        action: str,
        *,
        listener: OperationListener | None = None,
    ) -> WorkspaceOperationResult:
        operation = self._operation_for(action)
        value = self.runner.execute(action, operation, listener=listener)
        return WorkspaceOperationResult(action=action, value=value)

    def _operation_for(self, action: str) -> OperationCallable[object]:
        if action == "source.inspect":
            return lambda: inspect_repository(self.root, language=self.language)
        if action in {"report.generate", "report.refresh"}:
            return lambda: generate_report(self.root, language=self.language)
        if action == "report.open":
            return lambda: open_report(self.root)
        if action == "runtime.verify_mysql":
            return lambda: verify_mysql_repository(self.root)
        if action == "comparison.reconcile":
            return lambda: reconcile_repository(self.root)
        raise OperationActionError(action)


def _emit(
    listener: OperationListener | None,
    *,
    operation_id: str,
    operation_kind: str,
    phase_id: str,
    event_kind: str,
    safe_metadata: Mapping[str, SafeValue] | None = None,
) -> None:
    if listener is None:
        return
    try:
        listener(
            OperationEvent(
                operation_id=operation_id,
                operation_kind=operation_kind,
                phase_id=phase_id,
                event_kind=event_kind,
                monotonic_timestamp=time.monotonic(),
                safe_metadata=safe_metadata or {},
            )
        )
    except Exception:
        # Presentation observers are advisory. A broken observer must not turn
        # a successful artifact operation into a failed one.
        return


def _safe_metadata(values: Mapping[str, Any] | object) -> dict[str, SafeValue]:
    if not isinstance(values, Mapping):
        return {}
    safe: dict[str, SafeValue] = {}
    for key, value in values.items():
        if (
            str(key) not in _SAFE_METADATA_KEYS
            or _SENSITIVE_KEY.search(str(key))
            or not isinstance(value, _SAFE_TYPES)
        ):
            continue
        safe[str(key)] = value
    return safe


__all__ = [
    "OperationActionError",
    "OperationBusyError",
    "OperationEvent",
    "OperationRunner",
    "WorkspaceOperationResult",
    "WorkspaceOperationService",
]
