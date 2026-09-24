from contextvars import ContextVar

_current_request = ContextVar("rentmaster_current_request", default=None)


def get_current_request():
    return _current_request.get()


def get_current_user():
    request = get_current_request()
    user = getattr(request, "user", None)
    return user if user is not None and user.is_authenticated else None


class CurrentUserMiddleware:
    """Makes the acting user available to audit signals."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = _current_request.set(request)
        try:
            return self.get_response(request)
        finally:
            _current_request.reset(token)
