"""Lightweight in-memory metrics exposed as Prometheus text format.

No external dependencies — just counters and a histogram approximation.
Suitable for small deployments; swap with prometheus_client for production at scale.
"""

import time
import threading
from collections import defaultdict
from typing import Any


class Metrics:
    def __init__(self):
        self._lock = threading.Lock()
        self._counters: dict[str, int] = defaultdict(int)
        self._histogram_sum: dict[str, float] = defaultdict(float)
        self._histogram_count: dict[str, int] = defaultdict(int)

    def inc(self, name: str, labels: dict[str, str] | None = None, value: int = 1):
        key = self._key(name, labels)
        with self._lock:
            self._counters[key] += value

    def observe(self, name: str, value: float, labels: dict[str, str] | None = None):
        key = self._key(name, labels)
        with self._lock:
            self._histogram_sum[key] += value
            self._histogram_count[key] += 1

    def _key(self, name: str, labels: dict[str, str] | None) -> str:
        if not labels:
            return name
        label_str = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"

    def export(self) -> str:
        lines = []
        with self._lock:
            for key, val in sorted(self._counters.items()):
                lines.append(f"{key} {val}")
            for key in sorted(self._histogram_sum.keys()):
                lines.append(f"{key}_sum {self._histogram_sum[key]:.3f}")
                lines.append(f"{key}_count {self._histogram_count[key]}")
        return "\n".join(lines) + "\n"


metrics = Metrics()
