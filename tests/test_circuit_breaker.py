import time
import pytest
from src.infra.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError, CircuitState


class TestCircuitBreaker:

    def test_initial_state_closed(self):
        cb = CircuitBreaker(name="test")
        assert cb.state == CircuitState.CLOSED

    def test_trips_after_failures(self):
        cb = CircuitBreaker(name="test", failure_threshold=3, recovery_timeout=60)
        for _ in range(3):
            try:
                cb.call(lambda: (_ for _ in ()).throw(Exception("fail")))
            except Exception:
                pass
        assert cb.state == CircuitState.OPEN

    def test_open_circuit_raises(self):
        cb = CircuitBreaker(name="test", failure_threshold=1, recovery_timeout=60)
        try:
            cb.call(lambda: (_ for _ in ()).throw(Exception("fail")))
        except Exception:
            pass
        with pytest.raises(CircuitBreakerOpenError):
            cb.call(lambda: "ok")

    def test_half_open_recovers_on_success(self):
        cb = CircuitBreaker(name="test", failure_threshold=2, recovery_timeout=0.05, half_open_max_calls=1)
        for _ in range(2):
            try:
                cb.call(lambda: (_ for _ in ()).throw(Exception("fail")))
            except Exception:
                pass
        assert cb.state == CircuitState.OPEN
        time.sleep(0.06)
        result = cb.call(lambda: "recovered")
        assert result == "recovered"
        assert cb.state == CircuitState.CLOSED

    def test_half_open_fails_reopens(self):
        cb = CircuitBreaker(name="test", failure_threshold=2, recovery_timeout=0.05, half_open_max_calls=1)
        for _ in range(2):
            try:
                cb.call(lambda: (_ for _ in ()).throw(Exception("fail")))
            except Exception:
                pass
        assert cb.state == CircuitState.OPEN
        time.sleep(0.06)
        with pytest.raises(Exception):
            cb.call(lambda: (_ for _ in ()).throw(Exception("still fail")))
        assert cb.state == CircuitState.OPEN

    def test_reset(self):
        cb = CircuitBreaker(name="test", failure_threshold=1, recovery_timeout=60)
        try:
            cb.call(lambda: (_ for _ in ()).throw(Exception("fail")))
        except Exception:
            pass
        assert cb.state == CircuitState.OPEN
        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.stats.failure_count == 0

    def test_to_dict(self):
        cb = CircuitBreaker(name="test", failure_threshold=5, recovery_timeout=30)
        d = cb.to_dict()
        assert d["name"] == "test"
        assert d["state"] == "CLOSED"
        assert d["total_calls"] == 0
