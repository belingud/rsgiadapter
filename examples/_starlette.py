import logging
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.responses import PlainTextResponse

from rsgiadapter import ASGIToRSGI

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s [%(name)s.%(funcName)s:%(lineno)d] %(message)s",
)


@asynccontextmanager
async def lifespan(_app):
    print("lifespan start")
    yield
    print("lifespan stop")


async def hello(request):
    return PlainTextResponse("Hello World!")


application = Starlette(routes=[Route("/hello", hello)])

app = ASGIToRSGI(application, lifespan=lifespan)

if __name__ == "__main__":
    from granian import Granian

    server = Granian("_starlette:app")
    server.serve()
