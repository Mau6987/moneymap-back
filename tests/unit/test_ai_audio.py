"""El audio del dictado se lee una sola vez y no queda en ningún lado (spec 012, RF-10)."""

from pathlib import Path
from uuid import uuid4

import pytest

from app.core.config import get_settings
from app.modules.ai.infrastructure import audio


def test_el_worker_lee_el_audio_una_vez_y_lo_borra(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "voice_audio_dir", str(tmp_path / "voz"))
    entry_id = uuid4()

    audio.put(entry_id, b"RIFF...")

    assert audio.take(entry_id) == b"RIFF..."
    assert audio.take(entry_id) is None
    assert list((tmp_path / "voz").iterdir()) == []
