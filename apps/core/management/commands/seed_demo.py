"""Load demo data:  python manage.py seed_demo

Creates one login per role (password: Rentmaster@2026), a property with two
blocks, tenants, leases, several months of invoices and payments, arrears,
utilities, expenses and maintenance tickets.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import Role, User
from apps.billing import services
from apps.billing.models import DepositTransaction, Payment, PaymentMethod, UtilityReading
from apps.finance.models import Expense
from apps.maintenance.models import MaintenanceRequest, Vendor
from apps.properties.models import Building, Property, Unit
from apps.tenants.models import Lease, Tenant

PASSWORD = "Rentmaster@2026"


class Command(BaseCommand):
    help = "Populate the database with RENTMASTER demo data."

    def handle(self, *args, **options):
        if Property.objects.filter(code="ROYAL").exists():
            raise CommandError("Demo data already loaded.")
        with transaction.atomic():
            self._seed()
        self.stdout.write(self.style.SUCCESS(f"Demo data loaded. All demo logins use password: {PASSWORD}"))
        for u in User.objects.order_by("role"):
            self.stdout.write(f"  {u.get_role_display():28} {u.username}")

    def _user(self, username, role, first, last, **extra):
        user = User.objects.create_user(username=username, password=PASSWORD, role=role, first_name=first, last_name=last,
                                        email=f"{username}@example.com", **extra)
        return user

    def _seed(self):
        today = date.today()
        admin = self._user("admin", Role.SUPER_ADMIN, "System", "Admin", is_staff=True, is_superuser=True)
        owner = self._user("owner", Role.OWNER, "Grace", "Nakato", phone="+256772000001")
        manager = self._user("manager", Role.MANAGER, "Peter", "Okello", phone="+256772000002")
        self._user("accountant", Role.ACCOUNTANT, "Sarah", "Namuli")
        plumber = self._user("john", Role.MAINTENANCE, "John", "Mugisha", phone="+256772000004")
        caretaker = self._user("caretaker", Role.CARETAKER, "Moses", "Kato")

        royal = Property.objects.create(name="Royal Apartments", code="ROYAL", location="Ntinda, Kampala",
                                        latitude=Decimal("0.354300"), longitude=Decimal("32.614900"), owner=owner)
        royal.managers.add(manager, caretaker)
        heights = Property.objects.create(name="Kira Heights", code="KIRA", location="Kira, Wakiso", owner=owner,
                                          property_type=Property.Type.HOUSE)
        heights.managers.add(manager)

        units = {}
        for block, prefix, rent in (("Block A", "A", 600_000), ("Block B", "B", 700_000)):
            b = Building.objects.create(property=royal, name=block, floors=3)
            for n in range(1, 5):
                num = f"{prefix}10{n}"
                units[num] = Unit.objects.create(building=b, number=num, monthly_rent=rent, security_deposit=rent * 2,
                                                 unit_type=Unit.Type.TWO_BED if prefix == "B" else Unit.Type.ONE_BED,
                                                 electricity_meter=f"YAKA-{num}", water_meter=f"NWSC-{num}")
        kb = Building.objects.create(property=heights, name="Main", floors=1)
        for n in range(1, 4):
            units[f"K0{n}"] = Unit.objects.create(building=kb, number=f"K0{n}", monthly_rent=450_000, security_deposit=450_000,
                                                  unit_type=Unit.Type.TWO_BED)

        people = [
            ("Ronald Male", "+256772123456", "A102", 5, "full"),
            ("Aisha Nambi", "+256701234567", "A101", 7, "full"),
            ("Brian Ssemwogerere", "+256752345678", "A103", 4, "partial"),
            ("Christine Achieng", "+256782456789", "B101", 6, "behind"),
            ("David Tumusiime", "+256703567890", "B102", 3, "full"),
            ("Esther Nakimuli", "+256774678901", "K01", 10, "serious"),
            ("Frank Opio", "+256755789012", "K02", 2, "full"),
        ]
        start_base = services.add_months(today.replace(day=1), -5)
        for i, (name, phone, unit_no, months_ago, pattern) in enumerate(people):
            tenant = Tenant.objects.create(full_name=name, phone=phone, email=f"{name.split()[0].lower()}@example.com",
                                           national_id=f"CM9000{i}0012XYZ", occupation="Professional",
                                           emergency_contact_name="Next of kin", emergency_contact_phone="+256700000000")
            unit = units[unit_no]
            start = services.add_months(today.replace(day=1), -months_ago) if months_ago < 6 else start_base
            lease = Lease.objects.create(
                tenant=tenant, unit=unit, start_date=start, end_date=services.add_months(start, 12) - timedelta(days=1),
                monthly_rent=unit.monthly_rent, security_deposit=unit.security_deposit, due_day=5, grace_period_days=5,
                late_fee=20_000,
            )
            unit.status = Unit.Status.OCCUPIED
            unit.save()
            DepositTransaction.objects.create(lease=lease, kind="RECEIVED", amount=lease.security_deposit,
                                              description="Security deposit at move-in", date=start)
            if unit_no == "A102":
                tenant.user = self._user("ronald", Role.TENANT, "Ronald", "Male", phone=phone)
                tenant.save()
                UtilityReading.objects.create(unit=unit, utility="WATER", previous_reading=120, current_reading=132,
                                              rate=Decimal("2083.33"), meter_number=unit.water_meter, reading_date=start)
                UtilityReading.objects.create(unit=unit, utility="ELECTRICITY", previous_reading=4000, current_reading=4160,
                                              rate=250, meter_number=unit.electricity_meter, reading_date=start)

            # Bill every month up to today, then pay according to the pattern.
            d = start
            invoices = []
            while d <= today:
                inv, _ = services.create_invoice_for_lease(lease, d)
                invoices.append(inv)
                d = services.add_months(d, 1)
            for idx, inv in enumerate(invoices):
                is_current = idx == len(invoices) - 1
                if pattern == "full" or (pattern == "partial" and not is_current):
                    amount = inv.total
                elif pattern == "partial":
                    amount = inv.total // 2
                elif pattern == "behind":
                    amount = inv.total if idx < len(invoices) - 2 else 0
                else:  # serious
                    amount = inv.total if idx < len(invoices) - 3 else 0
                if pattern == "full" and is_current and name.startswith("Ronald"):
                    amount = 0  # Ronald has the current month outstanding for the portal demo
                if amount:
                    method = [PaymentMethod.MTN_MOMO, PaymentMethod.AIRTEL_MONEY, PaymentMethod.BANK, PaymentMethod.CASH][idx % 4]
                    p = Payment.objects.create(invoice=inv, amount=amount, method=method,
                                               payer_reference=f"TXN{inv.pk:06d}", payer_phone=phone, submitted_by=admin)
                    p = services.confirm_payment(p, verified_by=admin, provider_reference=f"PRV{inv.pk:08d}")
                    Payment.objects.filter(pk=p.pk).update(
                        verified_at=p.verified_at.replace(year=inv.due_date.year, month=inv.due_date.month, day=min(inv.due_date.day, 28)))

        # A pending bank payment to verify, from Christine.
        christine = Lease.objects.get(tenant__full_name="Christine Achieng")
        open_inv = christine.invoices.filter(status="UNPAID").first()
        if open_inv:
            Payment.objects.create(invoice=open_inv, amount=open_inv.total, method=PaymentMethod.BANK,
                                   payer_reference="STANBIC-88213", submitted_by=admin)

        services.apply_late_fees(today)

        vendor = Vendor.objects.create(name="Kampala Plumbing Ltd", trade="Plumber", phone="+256772555555")
        MaintenanceRequest.objects.create(unit=units["B103"], title="Water leakage", priority="HIGH", status="ASSIGNED",
                                          description="Water leaking under the kitchen sink.", assigned_to=plumber,
                                          vendor=vendor, reported_by=manager)
        MaintenanceRequest.objects.create(unit=units["A102"], title="Bathroom tap leaking", priority="MEDIUM",
                                          description="The bathroom tap is leaking.", reported_by=User.objects.get(username="ronald"))
        MaintenanceRequest.objects.create(unit=units["A101"], title="Broken window latch", priority="LOW", status="COMPLETED",
                                          description="Bedroom window latch broken.", assigned_to=plumber, cost=35_000,
                                          reported_by=caretaker)

        cats = [("REPAIRS", 1_200_000), ("SECURITY", 800_000), ("WATER", 400_000), ("ELECTRICITY", 300_000), ("OTHER", 200_000)]
        for m in range(0, 6):
            month = services.add_months(today.replace(day=1), -m)
            for cat, amount in cats:
                Expense.objects.create(property=royal, category=cat, amount=amount // (2 if m % 2 else 1),
                                       description=f"{cat.title()} {month:%b %Y}", date=month + timedelta(days=9))
        Expense.objects.create(property=heights, category="CLEANING", amount=150_000, description="Compound cleaning",
                               date=today.replace(day=1))

        # Vacancy with applications, and a move-in inspection for Ronald.
        from apps.inspections.models import DEFAULT_AREAS, Inspection, InspectionItem
        from apps.vacancies.models import Application, Listing

        listing = Listing.objects.create(unit=units["B104"], title="Spacious 2 bedroom at Royal Apartments, Ntinda",
                                         description="Tiled floors, balcony, secure parking, water tank. Close to Ntinda shopping centre.",
                                         monthly_rent=units["B104"].monthly_rent, created_by=manager)
        Application.objects.create(listing=listing, full_name="Joan Atim", phone="+256779111222", email="joan@example.com",
                                   occupation="Nurse", employer="Mulago Hospital", monthly_income=2_500_000,
                                   preferred_move_in=today + timedelta(days=14))
        Application.objects.create(listing=listing, full_name="Isaac Waiswa", phone="+256704333444",
                                   occupation="Trader", monthly_income=1_200_000, status=Application.Status.UNDER_REVIEW)
        ronald_lease = Lease.objects.get(unit=units["A102"])
        ins = Inspection.objects.create(unit=units["A102"], lease=ronald_lease, kind=Inspection.Kind.MOVE_IN,
                                        inspection_date=ronald_lease.start_date, inspector=caretaker)
        for area in DEFAULT_AREAS:
            InspectionItem.objects.create(inspection=ins, area=area,
                                          condition="NEEDS_REPAIR" if area == "Windows" else "GOOD",
                                          notes="Latch stiff" if area == "Windows" else "")
        ins.refresh_overall()
