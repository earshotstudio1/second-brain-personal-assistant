from __future__ import annotations

import unittest
import urllib.error

from pa_agent.telegram import NetworkRetry


class NetworkRetryTests(unittest.TestCase):
    def test_retries_transient_network_errors_then_succeeds(self) -> None:
        attempts = {"count": 0}
        sleeps: list[float] = []

        def flaky_transport() -> str:
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise ConnectionResetError("connection reset")
            return "ok"

        retry = NetworkRetry(initial=5.0, maximum=60.0, sleep=sleeps.append)
        result = retry.call(flaky_transport)

        self.assertEqual(result, "ok")
        self.assertEqual(attempts["count"], 3)
        # Two failures before success: 5s then 10s (doubling), capped at maximum.
        self.assertEqual(sleeps, [5.0, 10.0])

    def test_backoff_caps_at_maximum_and_resets_after_success(self) -> None:
        sleeps: list[float] = []
        calls = {"count": 0}

        def always_fails_then_stops() -> str:
            calls["count"] += 1
            if calls["count"] <= 4:
                raise urllib.error.URLError("network down")
            return "recovered"

        retry = NetworkRetry(initial=5.0, maximum=15.0, sleep=sleeps.append)
        result = retry.call(always_fails_then_stops)

        self.assertEqual(result, "recovered")
        # 5, 10, 15, 15 (capped) across the four failures.
        self.assertEqual(sleeps, [5.0, 10.0, 15.0, 15.0])

        # Backoff state resets to `initial` after a success.
        calls["count"] = 0

        def fails_once() -> str:
            calls["count"] += 1
            if calls["count"] == 1:
                raise ConnectionResetError("reset again")
            return "second ok"

        sleeps.clear()
        result2 = retry.call(fails_once)
        self.assertEqual(result2, "second ok")
        self.assertEqual(sleeps, [5.0])

    def test_non_network_exceptions_are_not_swallowed(self) -> None:
        retry = NetworkRetry(sleep=lambda _: None)

        def raises_value_error() -> None:
            raise ValueError("a genuine bug")

        with self.assertRaises(ValueError):
            retry.call(raises_value_error)


if __name__ == "__main__":
    unittest.main()
