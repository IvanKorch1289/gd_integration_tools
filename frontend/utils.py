import flet as ft
from aiohttp import ClientSession

from backend.core.settings import BASE_URL


class FletUtils:

    async def send_login_request(self, username, password):
        url = f"{BASE_URL}/auth/login/"
        headers = {"Content-Type": "application/json"}
        payload = {"username": username, "password": password}

        async with ClientSession() as session:
            async with session.get(url, params=payload, headers=headers) as response:
                if response.status == 200:
                    return await response.json()
                raise Exception("Ошибка входа")

    def get_cookie(self, name: str, page: ft.Page) -> str | None:
        self.show_snack_bar(page, page.session.get(name))
        return page.session.get(name)

    def show_snack_bar(self, page, message, color="#2196F3"):
        snack_bar = ft.SnackBar(
            content=ft.Text(
                value=message,
                size=20,  # Увеличиваем размер текста до 20 пикселей
                weight=ft.FontWeight.BOLD,  # Делаем текст жирным
            ),
            bgcolor=color,
        )
        page.overlay.append(snack_bar)
        snack_bar.open = True
        page.update()


flet_utils = FletUtils()
