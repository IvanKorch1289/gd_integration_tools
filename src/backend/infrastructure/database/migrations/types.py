from sqlalchemy_utils import types


def load_types():
    """Метод load_types (см. signature)."""
    return {"email": types.email.EmailType, "password": types.password.PasswordType}
