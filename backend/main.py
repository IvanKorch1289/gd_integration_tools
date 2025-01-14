from backend.core.app_factory import create_app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", reload=True, debug=True)
