from datetime import timedelta

from authx import AuthX, AuthXConfig
from settings import settings


config = AuthXConfig(
    JWT_SECRET_KEY=settings.auth_settings.auth_secret_key,
    JWT_ALGORITHM=settings.auth_settings.auth_algorithm,
    JWT_ACCESS_COOKIE_NAME=settings.auth_settings.auth_token_name,
    JWT_ACCESS_TOKEN_EXPIRES=timedelta(
        minutes=settings.auth_settings.auth_token_lifetime_seconds * 60
    ),
    JWT_TOKEN_LOCATION=["cookies"],
    JWT_COOKIE_CSRF_PROTECT=False,
)


security = AuthX(config=config)
