from __future__ import annotations

import logging
import time
import threading
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = auto()
    OPEN = auto()
    HALF_OPEN = auto()


@dataclass
class CircuitBreakerStats:
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: float = 0.0
    last_success_time: float = 0.0
    total_calls: int = 0
    total_failures: int = 0
    total_successes: int = 0


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 3,
        on_state_change: Optional[Callable[[str, CircuitState, CircuitState], None]] = None,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self.on_state_change = on_state_change

        self._state = CircuitState.CLOSED
        self._stats = CircuitBreakerStats()
        self._half_open_calls = 0
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        return self._state

    @property
    def stats(self) -> CircuitBreakerStats:
        return self._stats

    def call(self, fn: Callable, *args, **kwargs):
        with self._lock:
            if self._state == CircuitState.OPEN:
                if time.monotonic() - self._stats.last_failure_time >= self.recovery_timeout:
                    self._set_state(CircuitState.HALF_OPEN)
                    self._half_open_calls = 0
                else:
                    raise CircuitBreakerOpenError(
                        f"Circuit '{self.name}' is OPEN. "
                        f"{self.recovery_timeout - (time.monotonic() - self._stats.last_failure_time):.0f}s remaining"
                    )

            if self._state == CircuitState.HALF_OPEN and self._half_open_calls >= self.half_open_max_calls:
                raise CircuitBreakerOpenError(
                    f"Circuit '{self.name}' is HALF_OPEN and max probe calls reached"
                )

            self._stats.total_calls += 1
            if self._state == CircuitState.HALF_OPEN:
                self._half_open_calls += 1

        try:
            result = fn(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise

    def _on_success(self):
        with self._lock:
            self._stats.success_count += 1
            self._stats.total_successes += 1
            self._stats.last_success_time = time.monotonic()
            if self._state == CircuitState.HALF_OPEN:
                self._set_state(CircuitState.CLOSED)
                self._stats.failure_count = 0

    def _on_failure(self):
        with self._lock:
            self._stats.failure_count += 1
            self._stats.total_failures += 1
            self._stats.last_failure_time = time.monotonic()
            if self._state == CircuitState.CLOSED:
                if self._stats.failure_count >= self.failure_threshold:
                    self._set_state(CircuitState.OPEN)
            elif self._state == CircuitState.HALF_OPEN:
                self._set_state(CircuitState.OPEN)

    def _set_state(self, new_state: CircuitState):
        old_state = self._state
        self._state = new_state
        logger.info(
            "Circuit '%s': %s -> %s (failures=%d, successes=%d)",
            self.name, old_state.name, new_state.name,
            self._stats.failure_count, self._stats.success_count,
        )
        if self.on_state_change:
            self.on_state_change(self.name, old_state, new_state)

    def reset(self):
        with self._lock:
            self._set_state(CircuitState.CLOSED)
            self._stats = CircuitBreakerStats()

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "name": self.name,
                "state": self._state.name,
                "failure_count": self._stats.failure_count,
                "success_count": self._stats.success_count,
                "total_calls": self._stats.total_calls,
                "total_failures": self._stats.total_failures,
                "total_successes": self._stats.total_successes,
            }


class CircuitBreakerOpenError(Exception):
    pass
