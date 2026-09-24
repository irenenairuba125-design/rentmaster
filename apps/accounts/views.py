"""Login with optional two-factor authentication (TOTP)."""
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme

from apps.core.audit import log_action

from . import totp

MAX_ATTEMPTS = 5
SESSION_KEY = "rm_2fa_pending"


class RentmasterLoginView(LoginView):
    template_name = "registration/login.html"
    redirect_authenticated_user = True

    def form_valid(self, form):
        user = form.get_user()
        if not user.totp_enabled:
            return super().form_valid(form)
        # Password is correct, but the session is not logged in until the code is checked.
        self.request.session[SESSION_KEY] = {
            "user": user.pk, "backend": user.backend, "next": self.get_success_url(), "attempts": 0,
        }
        return redirect("login_2fa")


def login_2fa(request):
    pending = request.session.get(SESSION_KEY)
    if not pending:
        return redirect("login")
    error = None
    if request.method == "POST":
        user = get_user_model().objects.filter(pk=pending["user"], is_active=True).first()
        if user and totp.verify(user.totp_secret, request.POST.get("code")):
            del request.session[SESSION_KEY]
            login(request, user, backend=pending["backend"])
            nxt = pending.get("next") or settings.LOGIN_REDIRECT_URL
            if not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
                nxt = settings.LOGIN_REDIRECT_URL
            return redirect(nxt)
        pending["attempts"] += 1
        if pending["attempts"] >= MAX_ATTEMPTS:
            del request.session[SESSION_KEY]
            if user:
                log_action("Two-factor login failed: too many attempts", user, user=user)
            messages.error(request, "Too many incorrect codes. Please sign in again.")
            return redirect("login")
        request.session[SESSION_KEY] = pending
        error = "Incorrect code. Check your authenticator app and try again."
    return render(request, "registration/login_2fa.html", {"error": error})


@login_required
def two_factor_setup(request):
    user = request.user
    if user.totp_enabled:
        if request.method == "POST":
            if user.check_password(request.POST.get("password", "")) and totp.verify(user.totp_secret, request.POST.get("code")):
                user.totp_enabled = False
                user.totp_secret = ""
                user.save(update_fields=["totp_enabled", "totp_secret"])
                log_action("Disabled two-factor authentication", user)
                messages.success(request, "Two-factor authentication turned off.")
                return redirect("two_factor_setup")
            messages.error(request, "Password or code incorrect.")
        return render(request, "registration/two_factor.html", {"enabled": True})

    secret = request.session.get("rm_2fa_setup") or totp.new_secret()
    request.session["rm_2fa_setup"] = secret
    if request.method == "POST":
        if totp.verify(secret, request.POST.get("code")):
            user.totp_secret = secret
            user.totp_enabled = True
            user.save(update_fields=["totp_enabled", "totp_secret"])
            del request.session["rm_2fa_setup"]
            log_action("Enabled two-factor authentication", user)
            messages.success(request, "Two-factor authentication is on. You'll need a code from your app each time you sign in.")
            return redirect("dashboard")
        messages.error(request, "That code didn't match. Make sure your phone's clock is correct and try again.")
    return render(request, "registration/two_factor.html", {
        "enabled": False, "secret": secret,
        "uri": totp.provisioning_uri(secret, user.username, settings.RENTMASTER["COMPANY_NAME"]),
    })
