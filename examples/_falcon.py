import logging
from contextlib import asynccontextmanager

import falcon.asgi as asgi

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


class QuoteResource:
    async def on_get(self, req, resp):
        """Handle GET requests."""
        quote = {
            "author": "Grace Hopper",
            "quote": (
                "I've always been more interested in " "the future than in the past."
            ),
        }

        resp.media = quote


application = asgi.App()
application.add_route("/quote", QuoteResource())

app = ASGIToRSGI(application, lifespan=lifespan)

if __name__ == "__main__":
    from granian import Granian

    server = Granian("_falcon:app")
    server.serve()
