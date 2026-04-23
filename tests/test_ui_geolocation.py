from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from viewer.mixins.ui import UIMixin


class _SignalCollector:
    def __init__(self):
        self.calls = []

    def emit(self, payload):
        self.calls.append(payload)


class _Logger:
    def __init__(self):
        self.debug = MagicMock()
        self.warning = MagicMock()


class _UIGeolocationHarness(UIMixin):
    def __init__(self):
        self._map_loaded = False
        self._initial_map_pos = None
        self.signals = SimpleNamespace(update_map_signal=_SignalCollector())
        self.logger = _Logger()


def test_fetch_initial_position_stores_value_when_map_not_loaded():
    harness = _UIGeolocationHarness()

    with patch("viewer.mixins.ui.geocoder.ip", return_value=SimpleNamespace(latlng=[10.5, -20.75])):
        harness._fetch_initial_map_position_background()

    assert harness._initial_map_pos == (10.5, -20.75)
    assert harness.signals.update_map_signal.calls == []


def test_fetch_initial_position_emits_when_map_already_loaded():
    harness = _UIGeolocationHarness()
    harness._map_loaded = True

    with patch("viewer.mixins.ui.geocoder.ip", return_value=SimpleNamespace(latlng=[1.0, 2.0])):
        harness._fetch_initial_map_position_background()

    assert harness._initial_map_pos is None
    assert harness.signals.update_map_signal.calls == [[(1.0, 2.0)]]


def test_fetch_initial_position_handles_geocoder_exception():
    harness = _UIGeolocationHarness()

    with patch("viewer.mixins.ui.geocoder.ip", side_effect=RuntimeError("network down")):
        harness._fetch_initial_map_position_background()

    assert harness._initial_map_pos is None
    assert harness.signals.update_map_signal.calls == []
    harness.logger.warning.assert_called_once()
