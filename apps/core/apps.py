from django.apps import AppConfig, apps


class CoreConfig(AppConfig):
    name = "apps.core"

    # Models whose every create/update/delete is written to the audit trail.
    AUDITED = [
        "accounts.User",
        "properties.Property", "properties.Building", "properties.Unit",
        "tenants.Tenant", "tenants.Lease",
        "billing.Invoice", "billing.InvoiceItem", "billing.Payment", "billing.UtilityReading",
        "billing.DepositTransaction",
        "maintenance.MaintenanceRequest",
        "finance.Expense",
        "inspections.Inspection", "vacancies.Listing", "vacancies.Application",
    ]

    def ready(self):
        from . import audit

        audit.register(*(apps.get_model(label) for label in self.AUDITED))
