import logging
from contextlib import asynccontextmanager

from blacksheep.server import Application
from granian.constants import Interfaces

from rsgiadapter import ASGIToRSGI

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s [%(name)s.%(funcName)s:%(lineno)d] %(message)s",
)
sheep = Application()


@asynccontextmanager
async def lifespan(_app):
    print("lifespan startup")
    yield
    print("lifespan shutdown")


@sheep.router.get("/")
async def main():
    return "Hello, World!"


app = ASGIToRSGI(sheep, lifespan=lifespan)

if __name__ == "__main__":
    from granian import Granian

    server = Granian("_blacksheep:app", interface=Interfaces.RSGI)
    server.serve()
