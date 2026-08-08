from repoevidence.collectors.base import Collector


class CollectorRegistry:
    """An explicit registry for the collectors enabled in a scan."""

    def __init__(self) -> None:
        self._collectors: dict[str, Collector] = {}

    def register(self, collector: Collector) -> None:
        if collector.name in self._collectors:
            raise ValueError(f"Collector already registered: {collector.name}")
        self._collectors[collector.name] = collector

    @property
    def collectors(self) -> tuple[Collector, ...]:
        return tuple(self._collectors.values())
