from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator

import numpy as np


class CaptureSource(ABC):
    """A camera-like source. Yields (unix_ts, BGR frame) at most once per ``interval``.

    Implementations should avoid decoding frames that are not sampled.
    A future EmbeddedCameraSource only needs to implement this interface.
    """

    @abstractmethod
    def frames(self, interval: float) -> Iterator[tuple[float, np.ndarray]]: ...

    def progress(self) -> float | None:
        """0..1 for finite sources, None for live ones."""
        return None

    def close(self) -> None:  # pragma: no cover - default no-op
        pass
