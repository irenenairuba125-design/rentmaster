import csv
from datetime import date

from django.contrib import messages
from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import redirect, render

from apps.accounts.models import FINANCE_ROLES, Role
from apps.accounts.permissions import role_required
from apps.billing.models import Invoice, Payment
from apps.core.scoping import properties_for
from apps.properties.models import Unit

from .forms import ExpenseForm, ReportFilterForm
from .models import Expense

REPORT_ROLES = (*FINANCE_ROLES, Role.OWNER)


@role_required(*REPORT_ROLES)
def expense_list(request):
    expenses = Expense.objects.filter(property__in=properties_for(request.user)).select_related("property")
    category = request.GET.get("category", "")
    if category:
        expenses = expenses.filter(category=category)
    can_add = request.user.role in FINANCE_ROLES
    form = ExpenseForm(request.POST or None, request.FILES or None, user=request.user) if can_add else None
    if request.method == "POST" and can_add and form.is_valid():
        expense = form.save(commit=False)
        expense.recorded_by = request.user
        expense.save()
        messages.success(request, "Expense recorded.")
        return redirect("finance:expense_list")
    return render(request, "finance/expense_list.html", {
        "expenses": expenses[:500], "form": form, "category": category, "categories": Expense.Category.choices,
        "total": expenses.aggregate(s=Sum("amount"))["s"] or 0,
    })


def build_financial_report(props, start, end):
    """Income (verified cash received), billed, expenses and net per property."""
    rows = []
    for prop in props:
        payments = Payment.objects.filter(
            status=Payment.Status.VERIFIED, verified_at__date__gte=start, verified_at__date__lte=end,
            invoice__lease__unit__building__property=prop,
        )
        income = payments.aggregate(s=Sum("amount"))["s"] or 0
        billed = Invoice.objects.filter(
            lease__unit__building__property=prop, issue_date__gte=start, issue_date__lte=end,
        ).exclude(status=Invoice.Status.CANCELLED).aggregate(s=Sum("total"))["s"] or 0
        expenses = Expense.objects.filter(property=prop, date__gte=start, date__lte=end)
        by_cat = list(expenses.values("category").annotate(total=Sum("amount")).order_by("-total"))
        cat_labels = dict(Expense.Category.choices)
        for c in by_cat:
            c["label"] = cat_labels.get(c["category"], c["category"])
        expense_total = expenses.aggregate(s=Sum("amount"))["s"] or 0
        units = Unit.objects.filter(building__property=prop).aggregate(
            total=Count("pk"), occupied=Count("pk", filter=Q(status=Unit.Status.OCCUPIED)))
        rows.append({
            "property": prop, "billed": billed, "income": income, "expenses": expense_total, "net": income - expense_total,
            "by_category": by_cat, "units": units["total"], "occupied": units["occupied"],
            "occupancy": round(units["occupied"] * 100 / units["total"], 1) if units["total"] else 0,
            "collection_rate": round(income * 100 / billed, 1) if billed else None,
        })
    totals = {k: sum(r[k] for r in rows) for k in ("billed", "income", "expenses", "net", "units", "occupied")}
    totals["occupancy"] = round(totals["occupied"] * 100 / totals["units"], 1) if totals["units"] else 0
    return rows, totals


@role_required(*REPORT_ROLES)
def financial_report(request):
    form = ReportFilterForm(request.GET or None, user=request.user)
    today = date.today()
    start, end, prop = today.replace(day=1), today, None
    if form.is_valid():
        start, end, prop = form.cleaned_data["start"], form.cleaned_data["end"], form.cleaned_data["property"]
    props = properties_for(request.user)
    if prop:
        props = props.filter(pk=prop.pk)
    rows, totals = build_financial_report(props, start, end)

    if request.GET.get("format") == "csv":
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="financial-report-{start}-{end}.csv"'
        w = csv.writer(response)
        w.writerow(["Property", "Billed", "Collected", "Expenses", "Net income", "Units", "Occupied", "Occupancy %"])
        for r in rows:
            w.writerow([r["property"].name, r["billed"], r["income"], r["expenses"], r["net"], r["units"], r["occupied"], r["occupancy"]])
        w.writerow(["TOTAL", totals["billed"], totals["income"], totals["expenses"], totals["net"], totals["units"], totals["occupied"], totals["occupancy"]])
        return response
    return render(request, "finance/report.html", {"form": form, "rows": rows, "totals": totals, "start": start, "end": end})
