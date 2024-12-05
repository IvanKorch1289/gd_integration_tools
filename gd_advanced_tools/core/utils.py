from passlib.context import CryptContext
from pydantic import SecretStr


class Utilities:
    """Класс вспомогательных функций."""

    @classmethod
    def hash_password(cls, password):
        if isinstance(password, SecretStr):
            unsecret_password = password.get_secret_value()
        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        return pwd_context.hash(unsecret_password)


async def get_utils() -> Utilities:
    return Utilities()
