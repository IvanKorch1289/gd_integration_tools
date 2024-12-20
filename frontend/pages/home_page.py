from flet import Column, ElevatedButton, Page
from flet.core.text import Text


__all__ = ("HomePage",)


class HomePage:
    """Класс для отображения домашней страницы приложения."""

    def __init__(self, page: Page):
        """
        Конструктор класса HomePage.

        :param page: Объект страницы Flet.
        """
        self.page = page

    @property
    def content(self):
        """
        Свойство для создания содержимого домашней страницы.

        :return: Объект Column с содержимым домашней страницы.
        """
        return Column(
            controls=[
                Text(value="Welcome to the home page!"),
                ElevatedButton(text="Logout", on_click=self.logout),
            ]
        )

    def logout(self, _):
        """
        Метод для выполнения выхода из системы.

        :param _: Аргумент события, который не используется.
        """
        try:
            self.page.go("/")
        except Exception as e:
            print(f"Error during logout: {e}")
