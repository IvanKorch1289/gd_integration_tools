from flet import Column, ElevatedButton, Page, TextField
from flet.core.text import Text


__all__ = ("LoginForm",)


class LoginForm:
    def __init__(self, page: Page):
        self.page = page
        self.username = TextField(label="Username", hint_text="Enter your username")
        self.password = TextField(
            label="Password", hint_text="Enter your password", password=True
        )
        self.error_message = Text(value="", color="error")

    def build(self):
        self.content = Column(
            controls=[
                self.username,
                self.password,
                self.error_message,
                ElevatedButton("Login", on_click=self.authenticate),
            ],
            alignment="center",
        )
        return self.content

    async def authenticate(self, e):
        try:
            url = "http://yourserver.com/login"
            data = {"username": self.username.value, "password": self.password.value}
            headers = {"Content-Type": "application/json"}
            response = await self.page.http.post(url, json=data, headers=headers)

            if response.status == 200:
                self.page.go("/home")
            else:
                self.error_message.value = "Invalid username or password."
                self.page.update()
        except Exception as ex:
            self.error_message.value = "An error occurred while authenticating."
            self.page.update()
