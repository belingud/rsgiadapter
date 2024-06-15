from contextlib import asynccontextmanager

from rsgiadapter import ASGIToRSGI
from _django.asgi import application


@asynccontextmanager
async def lifespan(_app):
    print("lifespan start")
    yield
    print("lifespan stop")


app = ASGIToRSGI(application, lifespan=lifespan)


if __name__ == "__main__":
    from granian import Granian

    serve = Granian("serve:app")
    serve.serve()
