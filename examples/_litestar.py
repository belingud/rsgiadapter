import logging
from contextlib import asynccontextmanager

from litestar import Litestar, get

from rsgiadapter import ASGIToRSGI

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s [%(name)s.%(funcName)s:%(lineno)d] %(message)s",
)


@asynccontextmanager
async def lifespan(_app):
    print("lifespan startup")
    yield
    print("lifespan shutdown")


@get("/")
async def handler() -> str:
    return "Hello, World!"


star = Litestar(route_handlers=[handler])

app = ASGIToRSGI(star, lifespan=lifespan)

if __name__ == "__main__":
    from granian import Granian

    server = Granian("_litestar:app")
    server.serve()
