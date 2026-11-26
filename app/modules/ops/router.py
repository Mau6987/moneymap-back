from fastapi import APIRouter

# Logs e incidentes.
# Los endpoints y los casos de uso (application/) llegan con su spec; ver docs/adr/001-monolito-modular-cqrs.md.
router = APIRouter(tags=["ops"])
