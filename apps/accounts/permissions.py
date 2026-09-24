"""Role-based access control helpers used by views and the API."""
from functools import wraps

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied

from .models import Role


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                from django.contrib.auth.views import redirect_to_login
                return redirect_to_login(request.get_full_path())
            if request.user.role not in roles:
                raise PermissionDenied
            return view(request, *args, **kwargs)
        return wrapped
    return decorator


class RoleRequiredMixin(LoginRequiredMixin):
    allowed_roles = tuple(Role.values)

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.role not in self.allowed_roles:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)
