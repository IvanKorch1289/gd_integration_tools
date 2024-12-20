import flet as ft
from aiohttp import ClientSession

from backend.core.settings import BASE_URL


async def send_login_request(username, password):
    url = f"{BASE_URL}/auth/login/"
    headers = {"Content-Type": "application/json"}
    payload = {"username": username, "password": password}

    async with ClientSession() as session:
        async with session.get(url, params=payload, headers=headers) as response:
            if response.status == 200:
                return await response.json()
            raise Exception("Ошибка входа")


async def get_user_info(user_token: str):
    url = "http://127.0.0.1:8000/auth/me/"
    headers = {
        "Cookie": f"users_access_token={user_token}",
        "accept": "application/json",
    }
    async with ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            return response.json()


def show_snack_bar(page, message):
    snack_bar = ft.SnackBar(content=ft.Text(message))
    page.overlay.append(snack_bar)
    snack_bar.open = True
    page.update()
