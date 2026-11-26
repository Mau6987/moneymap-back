"""El SQL de `iam.users` y `iam.auth_identities`.

Los términos y el correo repetido no se validan aquí: los aplican el CHECK, el
índice único y el trigger de `iam.users` (constitución §3). Lo único que hace
este repositorio es insertar y leer lo que quedó.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.modules.iam.domain.models import NewUser, PasswordIdentity, ProfileChanges, SocialIdentity, UserProfile

# display_name lo completa el trigger con el nombre si viene vacío (RF-11).
_INSERT_USER = text(
    """
    INSERT INTO iam.users (email, first_name, last_name, display_name, terms_version, email_verified_at)
    VALUES (:email, :first_name, :last_name, :first_name, :terms_version, :email_verified_at)
    RETURNING id, email, first_name, last_name, display_name,
              avatar_object_key, country_code, city, occupation, locale, timezone, is_admin
    """
)

_INSERT_PASSWORD_IDENTITY = text(
    """
    INSERT INTO iam.auth_identities (user_id, provider, provider_subject, password_hash)
    VALUES (:user_id, 'password', :email, :password_hash)
    """
)

# Una cuenta de Google: sin contraseña. La clave (user_id, provider) impide dos.
_INSERT_PROVIDER_IDENTITY = text(
    """
    INSERT INTO iam.auth_identities (user_id, provider, provider_subject)
    VALUES (:user_id, :provider, :provider_subject)
    """
)

# El correo es citext: la comparación no distingue mayúsculas.
_FIND_PASSWORD_IDENTITY = text(
    """
    SELECT users.id AS user_id, identities.password_hash, users.email_verified_at
    FROM iam.users AS users
    JOIN iam.auth_identities AS identities
      ON identities.user_id = users.id AND identities.provider = 'password'
    WHERE users.email = :email AND users.deleted_at IS NULL AND users.status IN ('active', 'pending_deletion')
    """
)

_SET_PASSWORD = text(
    """
    UPDATE iam.auth_identities
    SET password_hash = :password_hash, last_used_at = :now
    WHERE user_id = :user_id AND provider = 'password'
    """
)

_FIND_ID_BY_EMAIL = text("SELECT id FROM iam.users WHERE email = :email AND deleted_at IS NULL")

# Una cuenta con el borrado pendiente entra: entrar lo cancela (RF-30). Una
# suspendida no, aunque la identidad exista.
_FIND_SIGN_IN_ID_BY_EMAIL = text(
    """
    SELECT id FROM iam.users
    WHERE email = :email AND deleted_at IS NULL AND status IN ('active', 'pending_deletion')
    """
)

_FIND_SIGN_IN_ID_BY_IDENTITY = text(
    """
    SELECT identities.user_id
    FROM iam.auth_identities AS identities
    JOIN iam.users AS users ON users.id = identities.user_id
    WHERE identities.provider = :provider AND identities.provider_subject = :provider_subject
      AND users.deleted_at IS NULL AND users.status IN ('active', 'pending_deletion')
    """
)

_FIND_PASSWORD_HASH = text(
    "SELECT password_hash FROM iam.auth_identities WHERE user_id = :user_id AND provider = 'password'"
)

_HAS_IDENTITY = text(
    """
    SELECT 1 FROM iam.auth_identities
    WHERE user_id = :user_id AND provider = :provider AND provider_subject = :provider_subject
    """
)

# El CHECK `users_deletion_requested_chk` exige que el estado y la fecha vayan juntos.
_SCHEDULE_DELETION = text(
    """
    UPDATE iam.users SET status = 'pending_deletion', deletion_requested_at = :now
    WHERE id = :user_id AND status = 'active'
    """
)

_CANCEL_DELETION = text(
    """
    UPDATE iam.users SET status = 'active', deletion_requested_at = NULL
    WHERE id = :user_id AND status = 'pending_deletion'
    """
)

_SELECT_PROFILE = text(
    """
    SELECT id, email, first_name, last_name, display_name,
           avatar_object_key, country_code, city, occupation, locale, timezone, is_admin
    FROM iam.users
    WHERE id = :user_id AND deleted_at IS NULL
    """
)

# RF-10: cada campo con su bandera, porque un None enviado borra el dato. Los
# espacios, el teléfono, el país en mayúsculas y el display_name vacío (RF-11)
# los normaliza el trigger iam.users_before_write.
_UPDATE_PROFILE = text(
    """
    UPDATE iam.users
    SET first_name = CASE WHEN :set_first_name THEN CAST(:first_name AS text) ELSE first_name END,
        last_name = CASE WHEN :set_last_name THEN CAST(:last_name AS text) ELSE last_name END,
        display_name = CASE WHEN :set_display_name THEN CAST(:display_name AS text) ELSE display_name END,
        country_code = CASE WHEN :set_country_code THEN CAST(:country_code AS text) ELSE country_code END,
        city = CASE WHEN :set_city THEN CAST(:city AS text) ELSE city END,
        occupation = CASE WHEN :set_occupation THEN CAST(:occupation AS text) ELSE occupation END,
        locale = CASE WHEN :set_locale THEN CAST(:locale AS text) ELSE locale END,
        timezone = CASE WHEN :set_timezone THEN CAST(:timezone AS text) ELSE timezone END
    WHERE id = :user_id AND deleted_at IS NULL
    RETURNING id, email, first_name, last_name, display_name,
              avatar_object_key, country_code, city, occupation, locale, timezone, is_admin
    """
)
_PROFILE_FIELDS = (
    "first_name",
    "last_name",
    "display_name",
    "country_code",
    "city",
    "occupation",
    "locale",
    "timezone",
)


class SqlUserRepository:
    """Implementa `UserRepository` sobre la sesión que le den."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, user: NewUser) -> UserProfile:
        row = (
            (
                await self._session.execute(
                    _INSERT_USER,
                    {
                        "email": user.email,
                        "first_name": user.first_name,
                        "last_name": user.last_name,
                        "terms_version": user.terms_version,
                        "email_verified_at": user.email_verified_at,
                    },
                )
            )
            .mappings()
            .one()
        )
        return _to_profile(row)

    async def append_password_identity(self, user_id: UUID, email: str, password_hash: str) -> None:
        await self._session.execute(
            _INSERT_PASSWORD_IDENTITY,
            {"user_id": user_id, "email": email, "password_hash": password_hash},
        )

    async def set_password(self, user_id: UUID, password_hash: str) -> None:
        await self._session.execute(
            _SET_PASSWORD,
            {"user_id": user_id, "password_hash": password_hash, "now": clock.utc_now()},
        )

    async def link_identity(self, user_id: UUID, social: SocialIdentity) -> None:
        await self._session.execute(
            _INSERT_PROVIDER_IDENTITY,
            {"user_id": user_id, "provider": social.provider, "provider_subject": social.subject},
        )

    async def find_id_by_email(self, email: str) -> UUID | None:
        return (await self._session.execute(_FIND_ID_BY_EMAIL, {"email": email})).scalar_one_or_none()

    async def find_sign_in_id_by_email(self, email: str) -> UUID | None:
        return (await self._session.execute(_FIND_SIGN_IN_ID_BY_EMAIL, {"email": email})).scalar_one_or_none()

    async def find_sign_in_id_by_identity(self, provider: str, subject: str) -> UUID | None:
        return (
            await self._session.execute(
                _FIND_SIGN_IN_ID_BY_IDENTITY, {"provider": provider, "provider_subject": subject}
            )
        ).scalar_one_or_none()

    async def find_password_hash(self, user_id: UUID) -> str | None:
        return (await self._session.execute(_FIND_PASSWORD_HASH, {"user_id": user_id})).scalar_one_or_none()

    async def has_identity(self, user_id: UUID, provider: str, subject: str) -> bool:
        params = {"user_id": user_id, "provider": provider, "provider_subject": subject}
        return (await self._session.execute(_HAS_IDENTITY, params)).scalar_one_or_none() is not None

    async def schedule_deletion(self, user_id: UUID, now: datetime) -> None:
        await self._session.execute(_SCHEDULE_DELETION, {"user_id": user_id, "now": now})

    async def cancel_deletion(self, user_id: UUID) -> None:
        await self._session.execute(_CANCEL_DELETION, {"user_id": user_id})

    async def find_password_identity(self, email: str) -> PasswordIdentity | None:
        row = (await self._session.execute(_FIND_PASSWORD_IDENTITY, {"email": email})).mappings().one_or_none()
        if row is None:
            return None
        return PasswordIdentity(
            user_id=row["user_id"],
            password_hash=row["password_hash"],
            email_verified_at=row["email_verified_at"],
        )

    async def get_profile(self, user_id: UUID) -> UserProfile | None:
        row = (await self._session.execute(_SELECT_PROFILE, {"user_id": user_id})).mappings().one_or_none()
        if row is None:
            return None
        return _to_profile(row)

    async def update_profile(self, user_id: UUID, changes: ProfileChanges) -> UserProfile | None:
        params: dict[str, object] = {"user_id": user_id}
        for field in _PROFILE_FIELDS:
            params[field] = getattr(changes, field)
            params[f"set_{field}"] = field in changes.sent
        row = (await self._session.execute(_UPDATE_PROFILE, params)).mappings().one_or_none()
        return None if row is None else _to_profile(row)

    async def email_taken(self, email: str) -> bool:
        return await self.find_id_by_email(email) is not None


def _to_profile(row: RowMapping) -> UserProfile:
    return UserProfile(
        id=row["id"],
        email=row["email"],
        first_name=row["first_name"],
        last_name=row["last_name"],
        display_name=row["display_name"],
        avatar_object_key=row["avatar_object_key"],
        country_code=row["country_code"],
        city=row["city"],
        occupation=row["occupation"],
        locale=row["locale"],
        timezone=row["timezone"],
        is_admin=row["is_admin"],
    )
