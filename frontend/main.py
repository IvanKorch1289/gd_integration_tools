import flet as ft

from frontend.pages import HomePage, LoginForm


def main(page: ft.Page):
    view = ft.View("/", controls=[LoginForm(page).build()])

    def route_change(route):
        view.controls.clear()
        if route == "/":
            view.controls.append(LoginForm(page).build())
        elif route == "/home":
            view.controls.append(HomePage(page).build())
        page.update()

    page.on_route_change = route_change
    page.go(page.route)
    page.views.append(view)


if __name__ == "__main__":
    ft.app(target=main)
