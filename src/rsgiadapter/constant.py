from enum import StrEnum

DEFAULT_ASGI_VERSION = "3.0"
DEFAULT_SPEC_VERSION = "2.3"


class EventTypeEnum(StrEnum):
    """
    ASGI event types
    """

    # http
    HTTP_REQUEST = "http.request"
    HTTP_DISCONNECT = "http.disconnect"
    HTTP_RESP_START = "http.response.start"
    HTTP_RESP_END = "http.response.end"
    HTTP_RESP_BODY = "http.response.body"

    # websocket
    WEBSOCKET_CONNECT = "websocket.connect"
    WEBSOCKET_DISCONNECT = "websocket.disconnect"
    WEBSOCKET_RECEIVE = "websocket.receive"
    WEBSOCKET_SEND = "websocket.send"

    # extensions
    PATH_SEND = "http.response.pathsend"
