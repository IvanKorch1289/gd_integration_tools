import flet as ft

from frontend.utils import flet_utils


__all__ = ("LoginPage",)


class LoginPage:
    def __init__(self, page, on_success):
        self.page = page
        self.on_success = on_success
        self.username_field = ft.TextField(
            label="Username",
            width=300,
            keyboard_type=ft.KeyboardType.EMAIL,
            value="user_007",
        )
        self.password_field = ft.TextField(
            label="Пароль",
            width=300,
            password=True,
            can_reveal_password=True,
            value="string",
        )

    @property
    def content(self):
        """
        Свойство для создания содержимого страницы аутентификации.

        :return: Объект Column с содержимым домашней страницы.
        """
        return ft.Column(
            [
                ft.Text("Вход", size=24, weight=ft.FontWeight.BOLD, color="#333"),
                self.username_field,
                self.password_field,
                ft.ElevatedButton(
                    text="Войти",
                    width=300,
                    bgcolor="#6200EE",
                    color="white",
                    on_click=self.on_login,
                ),
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=10,
        )

    async def on_login(self, e):
        if not self.username_field.value or not self.password_field.value:
            flet_utils.show_snack_bar(
                page=self.page,
                message="Заполните все поля для входа",
                color="#FF5722",  # Красный цвет
            )
            return

        await self.process_login(self.username_field.value, self.password_field.value)

    async def process_login(self, username, password):
        try:
            response = await flet_utils.send_login_request(username, password)
            if response.get("access_token"):
                self.page.session.set("access_token", response.get("access_token"))
                flet_utils.show_snack_bar(
                    page=self.page,
                    message=response.get("message", "Вход успешно выполнен!"),
                    color="#4CAF50",  # Зеленый цвет
                )
                self.clear_fields()
                await self.on_success()
            else:
                flet_utils.show_snack_bar(
                    page=self.page,
                    message=response.get("message", "Ошибка авторизации."),
                    color="#FF5722",  # Красный цвет
                )
        except Exception as ex:
            flet_utils.show_snack_bar(
                page=self.page, message=str(ex), color="#FF5722"  # Красный цвет
            )

    def clear_fields(self):
        self.username_field.value = ""
        self.password_field.value = ""
        self.page.update()

    async def display(self, e):
        self.page.clean()
        self.page.add(self.content)
