"""REST API (for the future Flutter app). Every queryset goes through the same
role scoping as the web UI."""
from rest_framework import mixins, permissions, serializers, status, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.response import Response

from apps.accounts.models import Role
from apps.billing import services as billing
from apps.billing.gateways import GatewayError, GatewayNotConfigured
from apps.billing.models import MOBILE_MONEY_METHODS, Invoice, InvoiceItem, Payment
from apps.maintenance.models import MaintenanceRequest
from apps.properties.models import Property, Unit
from apps.tenants.models import Lease

from .scoping import invoices_for, leases_for, maintenance_for, payments_for, properties_for, units_for


class PropertySerializer(serializers.ModelSerializer):
    class Meta:
        model = Property
        fields = ["id", "name", "code", "property_type", "location", "latitude", "longitude", "status"]


class UnitSerializer(serializers.ModelSerializer):
    property = serializers.CharField(source="building.property.name", read_only=True)
    building = serializers.CharField(source="building.name", read_only=True)

    class Meta:
        model = Unit
        fields = ["id", "number", "property", "building", "unit_type", "monthly_rent", "security_deposit", "status"]


class LeaseSerializer(serializers.ModelSerializer):
    tenant = serializers.CharField(source="tenant.full_name", read_only=True)
    unit = serializers.CharField(source="unit.number", read_only=True)

    class Meta:
        model = Lease
        fields = ["id", "tenant", "unit", "start_date", "end_date", "monthly_rent", "payment_frequency", "due_day", "status"]


class InvoiceItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceItem
        fields = ["category", "description", "amount"]


class InvoiceSerializer(serializers.ModelSerializer):
    items = InvoiceItemSerializer(many=True, read_only=True)
    balance = serializers.DecimalField(max_digits=12, decimal_places=0, read_only=True)
    unit = serializers.CharField(source="lease.unit.number", read_only=True)

    class Meta:
        model = Invoice
        fields = ["id", "number", "unit", "period_start", "period_end", "issue_date", "due_date", "total", "amount_paid",
                  "balance", "status", "items"]


class PaymentSerializer(serializers.ModelSerializer):
    invoice = serializers.CharField(source="invoice.number", read_only=True)
    receipt = serializers.CharField(source="receipt.number", read_only=True, default=None)

    class Meta:
        model = Payment
        fields = ["id", "invoice", "amount", "method", "status", "provider_reference", "created_at", "verified_at", "receipt"]


class MaintenanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = MaintenanceRequest
        fields = ["id", "ticket", "unit", "title", "description", "priority", "status", "created_at"]
        read_only_fields = ["ticket", "status", "created_at"]

    def validate_unit(self, unit):
        if not units_for(self.context["request"].user).filter(pk=unit.pk).exists():
            raise serializers.ValidationError("You cannot report issues for this unit.")
        return unit


class ScopedViewSet(viewsets.ReadOnlyModelViewSet):
    scope = None

    def get_queryset(self):
        return type(self).scope(self.request.user)


class PropertyViewSet(ScopedViewSet):
    serializer_class = PropertySerializer
    scope = staticmethod(properties_for)


class UnitViewSet(ScopedViewSet):
    serializer_class = UnitSerializer
    scope = staticmethod(lambda u: units_for(u).select_related("building__property"))


class LeaseViewSet(ScopedViewSet):
    serializer_class = LeaseSerializer
    scope = staticmethod(lambda u: leases_for(u).select_related("tenant", "unit"))


class PayInvoiceSerializer(serializers.Serializer):
    method = serializers.ChoiceField(choices=[(m.value, m.label) for m in MOBILE_MONEY_METHODS])
    amount = serializers.DecimalField(max_digits=12, decimal_places=0, min_value=500)
    phone = serializers.CharField(max_length=20)

    def validate_amount(self, amount):
        if amount > self.context["invoice"].balance:
            raise serializers.ValidationError(f"The outstanding balance is only {int(self.context['invoice'].balance):,}.")
        return amount


class InvoiceViewSet(ScopedViewSet):
    serializer_class = InvoiceSerializer
    scope = staticmethod(lambda u: invoices_for(u).select_related("lease__unit").prefetch_related("items"))

    @action(detail=True, methods=["post"])
    def pay(self, request, pk=None):
        """Tenant starts a mobile-money payment. The payment stays PENDING until the
        provider confirms it; poll POST /api/payments/<id>/check/."""
        if request.user.role != Role.TENANT:
            return Response({"detail": "Only tenants can pay through the app."}, status=status.HTTP_403_FORBIDDEN)
        invoice = self.get_object()
        if invoice.status not in (Invoice.Status.UNPAID, Invoice.Status.PARTIAL):
            return Response({"detail": "This invoice is not open."}, status=status.HTTP_400_BAD_REQUEST)
        ser = PayInvoiceSerializer(data=request.data, context={"invoice": invoice})
        ser.is_valid(raise_exception=True)
        from apps.billing.views import _callback_url

        note = "A payment prompt was sent to your phone. Enter your PIN to approve."
        try:
            payment = billing.initiate_mobile_money(invoice, ser.validated_data["amount"], ser.validated_data["method"],
                                                    ser.validated_data["phone"], request.user, callback_url_for=_callback_url)
        except GatewayNotConfigured:
            payment = invoice.payments.latest("created_at")
            note = "Online collection is not enabled yet; the accounts office will confirm this payment."
        except GatewayError:
            return Response({"detail": "The payment provider could not process the request. Try again."},
                            status=status.HTTP_502_BAD_GATEWAY)
        return Response({"payment": PaymentSerializer(payment).data, "detail": note}, status=status.HTTP_201_CREATED)


class PaymentViewSet(ScopedViewSet):
    serializer_class = PaymentSerializer
    scope = staticmethod(lambda u: payments_for(u).select_related("invoice", "receipt"))

    @action(detail=True, methods=["post"])
    def check(self, request, pk=None):
        """Ask the provider for the real status. Nothing the app sends can mark a payment paid."""
        payment = self.get_object()
        try:
            payment = billing.check_payment_status(payment)
        except GatewayNotConfigured:
            pass
        except GatewayError:
            return Response({"detail": "Could not reach the payment provider."}, status=status.HTTP_502_BAD_GATEWAY)
        payment = Payment.objects.select_related("invoice").get(pk=payment.pk)
        return Response(PaymentSerializer(payment).data)


class CanReportMaintenance(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user.role in (Role.SUPER_ADMIN, Role.MANAGER, Role.CARETAKER, Role.TENANT)


class MaintenanceViewSet(mixins.CreateModelMixin, ScopedViewSet):
    serializer_class = MaintenanceSerializer
    permission_classes = [permissions.IsAuthenticated, CanReportMaintenance]
    scope = staticmethod(maintenance_for)

    def perform_create(self, serializer):
        serializer.save(reported_by=self.request.user)


@api_view(["GET"])
def me(request):
    """Who am I, and (for tenants) what do I owe - the AI assistant / mobile app entry point."""
    user = request.user
    data = {"username": user.username, "name": str(user), "role": user.role}
    tenant = getattr(user, "tenant_profile", None)
    if tenant is not None:
        open_invoices = invoices_for(user).filter(status__in=[Invoice.Status.UNPAID, Invoice.Status.PARTIAL])
        lease = tenant.active_lease
        data.update({
            "tenant_id": tenant.tenant_id,
            "unit": lease.unit.number if lease else None,
            "monthly_rent": lease.monthly_rent if lease else None,
            "balance": sum(i.balance for i in open_invoices),
            "open_invoices": InvoiceSerializer(open_invoices, many=True).data,
        })
    return Response(data)
