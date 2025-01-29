from sqlalchemy_utils import types


def load_types():
    return {
        "email": types.email.EmailType,
        "password": types.password.PasswordType,
    }
