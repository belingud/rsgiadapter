import logging
from contextlib import asynccontextmanager

from quart import Quart

from rsgiadapter import ASGIToRSGI

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s [%(name)s.%(funcName)s:%(lineno)d] %(message)s",
)
application = Quart(__name__)


@asynccontextmanager
async def lifespan(_app):
    print("lifespan startup")
    yield
    print("lifespan shutdown")


@application.route("/")
async def index():
    return "Hello World!"


app = ASGIToRSGI(application, lifespan=lifespan)

if __name__ == "__main__":
    from granian import Granian

    serve = Granian("_quart:app")
    serve.serve()
