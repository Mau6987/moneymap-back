"""La página que ve quien abre el link del correo (RF-24).

Se abre en el navegador del teléfono, no en la app: por eso es HTML y no
problem+json. Sigue el estilo de los mockups 03 (fondo #EEF0F3, Manrope, el
ícono en un círculo con dos anillos) y le dice a la persona que vuelva a la app.
"""

from dataclasses import dataclass
from html import escape

from app.modules.iam.domain.models import VerificationStatus


@dataclass(frozen=True, slots=True)
class _Page:
    status_code: int
    color: str
    ring: str
    icon: str
    title: str
    message: str


_CHECK = '<path d="M20 6 9 17l-5-5"/>'
_CLOCK = '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>'
_ALERT = '<circle cx="12" cy="12" r="10"/><path d="M12 8v4M12 16h.01"/>'

_PAGES: dict[VerificationStatus | None, _Page] = {
    VerificationStatus.VERIFIED: _Page(
        200,
        "#2E8A62",
        "rgba(46,138,98,.12)",
        _CHECK,
        "Correo verificado",
        "Vuelve a MoneyMap y toca «Ya verifiqué · Continuar».",
    ),
    VerificationStatus.EXPIRED: _Page(
        410,
        "#D25A42",
        "rgba(210,90,66,.1)",
        _CLOCK,
        "El link expiró",
        "Dura 5 minutos. Pide otro desde la app.",
    ),
    None: _Page(
        404,
        "#D25A42",
        "rgba(210,90,66,.1)",
        _ALERT,
        "Este link no sirve",
        "Ya se usó o lo reemplazó uno más nuevo. Pide otro desde la app.",
    ),
}

_TEMPLATE = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>MoneyMap · {title}</title>
<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;600;800&amp;display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box}}
body{{margin:0;min-height:100vh;display:grid;place-items:center;padding:24px;
font-family:Manrope,system-ui,sans-serif;color:#151936;background:#EEF0F3;text-align:center}}
.hero{{position:relative;display:grid;place-items:center;width:140px;height:140px;margin:0 auto}}
.r{{position:absolute;border-radius:50%;background:{ring}}}
.r1{{inset:0}}.r2{{inset:18px}}
.c{{position:relative;display:grid;place-items:center;width:72px;height:72px;border-radius:24px;
background:{color};color:#fff}}
svg{{width:32px;height:32px;fill:none;stroke:currentColor;stroke-width:2.2;stroke-linecap:round;stroke-linejoin:round}}
h1{{margin:24px 0 0;font-size:28px;font-weight:800;letter-spacing:-.03em}}
p{{margin:8px 0 0;font-size:15px;color:#555B7E}}
.chip{{display:inline-block;margin-top:16px;padding:8px 14px;border-radius:17px;font-size:14px;font-weight:700;
background:rgba(255,255,255,.82);border:1px solid rgba(255,255,255,.95);
box-shadow:0 1px 2px rgba(21,25,54,.06),0 10px 24px -12px rgba(21,25,54,.18)}}
</style>
</head>
<body>
<main>
<div class="hero" aria-hidden="true"><div class="r r1"></div><div class="r r2"></div>
<span class="c"><svg viewBox="0 0 24 24">{icon}</svg></span></div>
<h1>{title}</h1>
<p>{message}</p>
{chip}
</main>
</body>
</html>
"""


def render_verify_page(status: VerificationStatus | None, email: str | None) -> tuple[int, str]:
    """El estado HTTP y el HTML. `status` None: el link no existe, ya se usó o fue reemplazado."""
    page = _PAGES.get(status, _PAGES[None])
    chip = f'<span class="chip">{escape(email)}</span>' if email and status is not None else ""
    html = _TEMPLATE.format(
        title=page.title,
        message=page.message,
        color=page.color,
        ring=page.ring,
        icon=page.icon,
        chip=chip,
    )
    return page.status_code, html
