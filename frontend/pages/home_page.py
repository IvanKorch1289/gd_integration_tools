from flet import Column, ElevatedButton, Page, UserControl
from flet.core.text import Text


__all__ = ("HomePage",)


class HomePage:
    def __init__(self, page: Page):
        self.page = page

    def build(self):
        self.content = Column(
            controls=[
                Text(value="Welcome to the home page!"),
                ElevatedButton("Logout", on_click=lambda _: self.logout()),
            ]
        )
        return self.content

    def logout(self):
        self.page.go("/")
