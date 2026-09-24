from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path, reverse_lazy
from django.views.generic import RedirectView
from rest_framework.routers import DefaultRouter

from apps.accounts import api_auth, views as account_views
from apps.core import api, documents, views as core_views

router = DefaultRouter()
router.register("properties", api.PropertyViewSet, basename="api-property")
router.register("units", api.UnitViewSet, basename="api-unit")
router.register("leases", api.LeaseViewSet, basename="api-lease")
router.register("invoices", api.InvoiceViewSet, basename="api-invoice")
router.register("payments", api.PaymentViewSet, basename="api-payment")
router.register("maintenance", api.MaintenanceViewSet, basename="api-maintenance")

admin.site.site_header = "RENTMASTER administration"

urlpatterns = [
    path("", core_views.dashboard, name="dashboard"),
    path("login/", account_views.RentmasterLoginView.as_view(), name="login"),
    path("login/verify/", account_views.login_2fa, name="login_2fa"),
    path("account/two-factor/", account_views.two_factor_setup, name="two_factor_setup"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("password/", auth_views.PasswordChangeView.as_view(template_name="form.html", success_url="/",
                                                            extra_context={"title": "Change password"}), name="password_change"),
    path("notifications/", core_views.notifications, name="notifications"),
    path("notifications/<int:pk>/open/", core_views.notification_open, name="notification_open"),
    path("audit/", core_views.audit_log, name="audit_log"),
    path("announcements/new/", core_views.announcement, name="announcement"),
    path("my-documents/", documents.my_documents, name="my_documents"),
    path("files/tenant-document/<int:pk>/", documents.tenant_document, name="tenant_document"),
    path("files/tenant-photo/<int:pk>/", documents.tenant_photo, name="tenant_photo"),
    path("files/lease-agreement/<int:pk>/", documents.lease_agreement, name="lease_agreement"),
    path("files/property-document/<int:pk>/", documents.property_document, name="property_document"),
    path("files/expense-receipt/<int:pk>/", documents.expense_receipt, name="expense_receipt"),
    path("inspections/", include("apps.inspections.urls")),
    path("vacancies/", include("apps.vacancies.urls")),
    path("properties/", include("apps.properties.urls")),
    path("tenants/", include("apps.tenants.urls")),
    path("billing/", include("apps.billing.urls")),
    path("maintenance/", include("apps.maintenance.urls")),
    path("finance/", include("apps.finance.urls")),
    path("api/auth/login/", api_auth.api_login, name="api-login"),
    path("api/auth/logout/", api_auth.api_logout, name="api-logout"),
    path("api/me/", api.me, name="api-me"),
    path("api/", include(router.urls)),
    # Admin sign-in goes through the main login so two-factor authentication applies.
    path("admin/login/", RedirectView.as_view(url=reverse_lazy("login"), query_string=True)),
    path("admin/", admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
