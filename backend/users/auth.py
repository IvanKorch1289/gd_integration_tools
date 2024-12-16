from authx import AuthX, AuthXConfig

from backend.core.settings import settings


config = AuthXConfig(
    JWT_SECRET_KEY=settings.auth_settings.auth_secret_key,
    JWT_ALGORITHM=settings.auth_settings.auth_algorithm,
    JWT_ACCESS_COOKIE_NAME=settings.auth_settings.auth_token_name,
    JWT_TOKEN_LOCATION=["cookies"],
)


security = AuthX(config=config)
