import uuid
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum

from apps.core.models import Sequence
from apps.properties.models import Unit
from apps.tenants.models import Lease


class ChargeCategory(models.TextChoices):
    RENT = "RENT", "Rent"
    WATER = "WATER", "Water"
    ELECTRICITY = "ELECTRICITY", "Electricity"
    GARBAGE = "GARBAGE", "Garbage"
    SECURITY = "SECURITY", "Security"
    INTERNET = "INTERNET", "Internet"
    CLEANING = "CLEANING", "Cleaning"
    LATE_FEE = "LATE_FEE", "Late fee"
    OTHER = "OTHER", "Other"


class Invoice(models.Model):
    class Status(models.TextChoices):
        UNPAID = "UNPAID", "Unpaid"
        PARTIAL = "PARTIAL", "Partially paid"
        PAID = "PAID", "Paid"
        CANCELLED = "CANCELLED", "Cancelled"

    number = models.CharField(max_length=30, unique=True, editable=False)
    lease = models.ForeignKey(Lease, on_delete=models.PROTECT, related_name="invoices")
    period_start = models.DateField()
    period_end = models.DateField()
    issue_date = models.DateField(default=date.today)
    due_date = models.DateField()
    total = models.DecimalField(max_digits=12, decimal_places=0, default=0, editable=False)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=0, default=0, editable=False)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.UNPAID)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-issue_date", "-number"]
        constraints = [
            models.UniqueConstraint(
                fields=["lease", "period_start"],
                condition=~models.Q(status="CANCELLED"),
                name="one_live_invoice_per_lease_period",
            )
        ]

    def save(self, *args, **kwargs):
        if not self.number:
            year = self.issue_date.year
            self.number = f"INV-{year}-{Sequence.next(f'invoice-{year}'):05d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.number

    @property
    def balance(self):
        return max(self.total - self.amount_paid, Decimal(0))

    @property
    def grace_deadline(self):
        from datetime import timedelta
        return self.due_date + timedelta(days=self.lease.grace_period_days)

    @property
    def is_overdue(self):
        return self.status in (self.Status.UNPAID, self.Status.PARTIAL) and date.today() > self.due_date

    @property
    def days_overdue(self):
        return max((date.today() - self.due_date).days, 0) if self.is_overdue else 0

    def recalculate(self, save=True):
        """Recompute totals from items and *verified* payments only."""
        self.total = self.items.aggregate(s=Sum("amount"))["s"] or 0
        self.amount_paid = self.payments.filter(status=Payment.Status.VERIFIED).aggregate(s=Sum("amount"))["s"] or 0
        if self.status != self.Status.CANCELLED:
            if self.total > 0 and self.amount_paid >= self.total:
                self.status = self.Status.PAID
            elif self.amount_paid > 0:
                self.status = self.Status.PARTIAL
            else:
                self.status = self.Status.UNPAID
        if save:
            self.save(update_fields=["total", "amount_paid", "status"])


class InvoiceItem(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="items")
    category = models.CharField(max_length=15, choices=ChargeCategory.choices)
    description = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=12, decimal_places=0)

    def __str__(self):
        return f"{self.description}: {self.amount}"


class UtilityReading(models.Model):
    class Utility(models.TextChoices):
        ELECTRICITY = "ELECTRICITY", "Electricity"
        WATER = "WATER", "Water"

    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name="utility_readings")
    utility = models.CharField(max_length=15, choices=Utility.choices)
    meter_number = models.CharField(max_length=40, blank=True)
    reading_date = models.DateField(default=date.today)
    previous_reading = models.DecimalField(max_digits=12, decimal_places=2)
    current_reading = models.DecimalField(max_digits=12, decimal_places=2)
    rate = models.DecimalField(max_digits=10, decimal_places=2, help_text="Price per unit consumed")
    invoice_item = models.OneToOneField(InvoiceItem, null=True, blank=True, on_delete=models.SET_NULL, editable=False)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, editable=False)

    class Meta:
        ordering = ["-reading_date"]

    def __str__(self):
        return f"{self.get_utility_display()} {self.unit.number} {self.reading_date}"

    @property
    def consumption(self):
        return self.current_reading - self.previous_reading

    @property
    def amount(self):
        return (self.consumption * self.rate).quantize(Decimal("1"))

    @property
    def is_billed(self):
        return self.invoice_item_id is not None


class PaymentMethod(models.TextChoices):
    MTN_MOMO = "MTN_MOMO", "MTN Mobile Money"
    AIRTEL_MONEY = "AIRTEL_MONEY", "Airtel Money"
    BANK = "BANK", "Bank transfer"
    CARD = "CARD", "Card"
    CASH = "CASH", "Cash"
    OTHER = "OTHER", "Other"


MOBILE_MONEY_METHODS = (PaymentMethod.MTN_MOMO, PaymentMethod.AIRTEL_MONEY)


class Payment(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending verification"
        VERIFIED = "VERIFIED", "Verified"
        FAILED = "FAILED", "Failed / rejected"

    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=12, decimal_places=0)
    method = models.CharField(max_length=15, choices=PaymentMethod.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    # Our own idempotency / correlation id sent to the provider.
    internal_reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    # Reference typed by the payer (bank slip no., MoMo transaction id...). Informational only:
    # a payment is never verified on the strength of this value alone.
    payer_reference = models.CharField(max_length=100, blank=True)
    # Reference confirmed by the provider's API.
    provider_reference = models.CharField(max_length=100, blank=True)
    payer_phone = models.CharField(max_length=20, blank=True)
    provider_response = models.JSONField(default=dict, blank=True)
    failure_reason = models.CharField(max_length=200, blank=True)
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_method_display()} {self.amount} for {self.invoice.number}"


class Receipt(models.Model):
    number = models.CharField(max_length=30, unique=True, editable=False)
    payment = models.OneToOneField(Payment, on_delete=models.PROTECT, related_name="receipt")
    verification_code = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    issued_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.number:
            year = date.today().year
            self.number = f"REC-{year}-{Sequence.next(f'receipt-{year}'):05d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.number


class DepositTransaction(models.Model):
    class Kind(models.TextChoices):
        RECEIVED = "RECEIVED", "Deposit received"
        DEDUCTION = "DEDUCTION", "Deduction"
        REFUND = "REFUND", "Refund"

    lease = models.ForeignKey(Lease, on_delete=models.PROTECT, related_name="deposit_transactions")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=0)
    description = models.CharField(max_length=200)
    date = models.DateField(default=date.today)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, editable=False)

    class Meta:
        ordering = ["date", "pk"]

    def __str__(self):
        return f"{self.get_kind_display()} {self.amount}"

    @staticmethod
    def held_for(lease):
        totals = {k: lease.deposit_transactions.filter(kind=k).aggregate(s=Sum("amount"))["s"] or 0
                  for k in DepositTransaction.Kind.values}
        return totals["RECEIVED"] - totals["DEDUCTION"] - totals["REFUND"]
