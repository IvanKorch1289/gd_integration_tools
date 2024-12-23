import flet as ft

from frontend.pages import HomePage, LoginPage


async def main(page: ft.Page):
    page.title = "Расширенные инструменты GreenData"
    page.vertical_alignment = ft.MainAxisAlignment.CENTER
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.padding = 20

    dark_theme = ft.Theme(
        color_scheme=ft.ColorScheme(
            primary=ft.colors.INDIGO_400,
            on_primary=ft.colors.WHITE,
            primary_container=ft.colors.INDIGO_700,
            on_primary_container=ft.colors.INDIGO_50,
            secondary=ft.colors.TEAL_300,
            on_secondary=ft.colors.BLACK,
            background=ft.colors.GREY_900,
            on_background=ft.colors.GREY_100,
            surface=ft.colors.GREY_900,
            on_surface=ft.colors.GREY_100,
            error=ft.colors.RED_400,
            on_error=ft.colors.WHITE,
            surface_tint=ft.colors.INDIGO_400,
            shadow=ft.colors.BLACK54,
        ),
        font_family="Inter",
        use_material3=True,
    )

    page.theme = dark_theme
    page.update()

    # Начальное состояние - страница логина
    state = "login"

    async def switch_to_home_page():
        nonlocal state
        state = "home"
        page.clean()
        home_page = HomePage(page, on_logout_callback=on_logout)
        await home_page.display()

    async def switch_to_login_page():
        nonlocal state
        state = "login"
        page.clean()
        login_page = LoginPage(page, on_success=switch_to_home_page)
        await login_page.display(e=None)

    async def on_logout():
        await switch_to_login_page()

    # Начальная отрисовка страницы логина
    await switch_to_login_page()


ft.app(target=main)
