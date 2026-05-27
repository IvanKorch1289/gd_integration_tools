import typer, sys

app = typer.Typer()

@app.command()
def cli(tenant_aware: bool = True) -> None:
    sys.stdout.write(f'RESULT:tenant_aware={tenant_aware}\n')
    sys.stdout.flush()

for args in [[], ['--tenant-aware'], ['--no-tenant-aware']]:
    sys.argv = ['test'] + args
    try:
        typer.run(app.callback()(cli), standalone=False)
    except SystemExit:
        pass