import logging

from sanic import Sanic
from sanic.response import json

from rsgiadapter import ASGIToRSGI

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s [%(name)s.%(funcName)s:%(lineno)d] %(message)s",
)
application = Sanic("demo")


@application.get("/api")
async def handler(request):
    return json({"hello": "world"})


app = ASGIToRSGI(application)


if __name__ == "__main__":
    from granian import Granian

    server = Granian("_sanic:app")
    server.serve()
