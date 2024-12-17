import flet as ft

from frontend.pages import HomePage, LoginForm


async def main(page: ft.Page):
    page.title = "Одностраничное приложение"
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

    main_app = HomePage(page)

    async def on_login_success():
        await main_app.display()

    login_form = LoginForm(page, on_success=on_login_success)

    await login_form.display(e=None)


ft.app(target=main)
