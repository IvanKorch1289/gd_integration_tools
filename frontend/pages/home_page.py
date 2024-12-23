import flet as ft

from backend.core.settings import settings
from frontend.utils import flet_utils


class HomePage:
    """Класс для отображения домашней страницы приложения."""

    def __init__(self, page: ft.Page, on_logout_callback):
        """
        Конструктор класса HomePage.

        :param page: Объект страницы Flet.
        """
        self.page = page
        self.on_logout_callback = on_logout_callback

    @property
    def content(self):
        """
        Свойство для создания содержимого домашней страницы.

        :return: Объект Column с содержимым домашней страницы.
        """
        return ft.Column(
            controls=[
                ft.Text(value="Добро пожаловать на домашнюю страницу!"),
                ft.ElevatedButton(
                    text="Перейти к хранилищу логов",
                    on_click=lambda e: self.button_clicked("Перейти к хранилищу логов"),
                ),
                ft.ElevatedButton(
                    text="Перейти к файловому хранилищу",
                    on_click=lambda e: self.button_clicked(
                        "Перейти к файловому хранилищу"
                    ),
                ),
                ft.ElevatedButton(
                    text="Перейти в документацию api",
                    on_click=lambda e: self.button_clicked(
                        "Перейти в документацию api"
                    ),
                ),
                ft.ElevatedButton(
                    text="Перейти в SQLAdmin",
                    on_click=lambda e: self.button_clicked("Перейти в SQLAdmin"),
                ),
                ft.ElevatedButton(
                    text="Перейти в менеджер задач",
                    on_click=lambda e: self.button_clicked("Перейти в менеджер задач"),
                ),
                ft.ElevatedButton(text="Выход", on_click=self.logout),
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def button_clicked(self, button_name):
        """
        Обработчик нажатия кнопки.

        :param button_name: Имя нажатой кнопки.
        """
        try:
            if button_name == "Перейти к хранилищу логов":
                self.open_new_tab(url=settings.logging_settings.log_interfaсe_url)
            elif button_name == "Перейти к файловому хранилищу":
                self.open_new_tab(url=settings.storage_settings.fs_interfase_url)
            elif button_name == "Перейти в документацию api":
                self.open_new_tab(url=settings.base_url + "/docs")
            elif button_name == "Перейти в SQLAdmin":
                self.open_new_tab(url=settings.base_url + "/admin")
            elif button_name == "Перейти в менеджер задач":
                self.open_new_tab(url=settings.bts_settings.bts_interface_url)
        except Exception as ex:
            flet_utils.show_snack_bar(
                page=self.page, message=str(ex), color="#FF5722"  # Красный цвет
            )

    def open_new_tab(self, url):
        """
        Открывает новую вкладку с указанной ссылкой.

        :param url: Ссылка для открытия в новой вкладке.
        """
        self.page.launch_url(url)

    def logout(self, e):
        """Метод для выполнения выхода из системы."""
        self.on_logout_callback()

    async def display(self):
        """
        Метод для отображения домашней страницы.
        """
        self.page.clean()
        self.page.add(self.content)
