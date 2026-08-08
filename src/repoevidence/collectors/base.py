from abc import ABC, abstractmethod
from pathlib import Path

from repoevidence.models import CollectorResult


class Collector(ABC):
    """Small interface implemented by each evidence collector."""

    name: str

    @abstractmethod
    def collect(self, repo_root: Path) -> CollectorResult:
        """Collect raw observations and derived facts for a repository."""
