import flet as ft
import httpx


async def send_login_request(email, password):
    url = "http://127.0.0.1:8000/auth/login/"
    headers = {"Content-Type": "application/json"}
    payload = {"email": email, "password": password}

    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=payload, headers=headers)
        if response.status == 200:
            return response.json()
        else:
            error_message = response.text()
            raise Exception(f"Ошибка входа: {error_message}")


async def get_user_info(user_token: str):
    url = "http://127.0.0.1:8000/auth/me/"
    headers = {
        "Cookie": f"users_access_token={user_token}",
        "accept": "application/json",
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        return response.json()


def show_snack_bar(page, message):
    snack_bar = ft.SnackBar(content=ft.Text(message))
    page.overlay.append(snack_bar)
    snack_bar.open = True
    page.update()
