"""El audio del dictado, de la API al worker (spec 012, RF-10).

No viaja en la cola: Redis guarda cada mensaje en disco (appendonly) y el audio
quedaría ahí hasta que compacte el archivo. Va a una carpeta que la API y el
worker comparten, que en docker-compose.yml es un tmpfs: está en memoria y no
sobrevive a un reinicio. El worker lo lee y lo borra antes de transcribir.
"""

import os
from pathlib import Path
from uuid import UUID

from app.core.config import get_settings


def _path(entry_id: UUID) -> Path:
    return Path(get_settings().voice_audio_dir) / str(entry_id)


def put(entry_id: UUID, audio: bytes) -> None:
    path = _path(entry_id)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as file:
        file.write(audio)


def take(entry_id: UUID) -> bytes | None:
    """El audio una sola vez: después ya no está. None si nunca llegó o se perdió."""
    path = _path(entry_id)
    try:
        audio = path.read_bytes()
    except FileNotFoundError:
        return None
    path.unlink(missing_ok=True)
    return audio
