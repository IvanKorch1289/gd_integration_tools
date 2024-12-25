import flet as ft


def main(page: ft.Page):
    # Получаем сессию
    session = page.session

    # Проверяем наличие токена в cookies
    token = session.get_cookie("auth_token")

    if not token or is_expired(token):
        login_view(page)
    else:
        authorized_view(page)


def login_view(page: ft.Page):
    def on_login_click(e):
        username = txt_username.value
        password = txt_password.value

        # Здесь должна быть логика проверки логина/пароля и получения токена
        token = get_auth_token(username, password)

        if token:
            # Сохранение токена в cookies
            session = page.session
            session.set_cookie("auth_token", token, expires_days=7)

            # Переход к авторизированному виду
            authorized_view(page)
        else:
            error_text.visible = True

    txt_username = ft.TextField(label="Логин", width=200)
    txt_password = ft.TextField(label="Пароль", password=True, width=200)
    btn_login = ft.ElevatedButton("Войти", on_click=on_login_click)
    error_text = ft.Text(
        value="Неверный логин или пароль!", visible=False, color="error"
    )

    page.add(ft.Column([txt_username, txt_password, btn_login, error_text]))


def authorized_view(page: ft.Page):
    def logout():
        # Удаление токена из cookies
        session = page.session
        session.delete_cookie("auth_token")

        # Возвращаемся к форме входа
        login_view(page)

    page.clean()
    page.add(
        ft.Row(
            [
                ft.ElevatedButton("Действие 1"),
                ft.ElevatedButton("Действие 2"),
                ft.IconButton(icon=ft.icons.LOGOUT, on_click=lambda _: logout()),
            ]
        )
    )


# Функция для проверки срока действия токена


def is_expired(token):
    # Реализуйте свою логику проверки срока действия токена
    return False


# Функция для получения токена авторизации


def get_auth_token(username, password):
    # Реализуйте свою логику аутентификации и получения токена
    return "1234567890abcdef"


if __name__ == "__main__":
    ft.app(target=main)
