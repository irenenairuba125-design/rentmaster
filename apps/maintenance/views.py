from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import Role
from apps.accounts.permissions import role_required
from apps.core.models import Notification
from apps.core.notify import notify_property_people, notify_user
from apps.core.scoping import maintenance_for

from .forms import MaintenanceCommentForm, MaintenanceRequestForm, MaintenanceUpdateForm
from .models import MaintenanceRequest

ALL = (Role.SUPER_ADMIN, Role.OWNER, Role.MANAGER, Role.ACCOUNTANT, Role.CARETAKER, Role.MAINTENANCE, Role.TENANT)
CREATE = (Role.SUPER_ADMIN, Role.MANAGER, Role.CARETAKER, Role.TENANT)
UPDATE = (Role.SUPER_ADMIN, Role.MANAGER, Role.CARETAKER, Role.MAINTENANCE)


@role_required(*ALL)
def request_list(request):
    qs = maintenance_for(request.user).select_related("unit__building__property", "assigned_to")
    status = request.GET.get("status", "OPEN")
    if status == "OPEN":
        qs = qs.exclude(status__in=[MaintenanceRequest.Status.COMPLETED, MaintenanceRequest.Status.CANCELLED])
    elif status:
        qs = qs.filter(status=status)
    return render(request, "maintenance/request_list.html", {
        "requests": qs, "status": status,
        "statuses": [("OPEN", "Open")] + MaintenanceRequest.Status.choices,
        "can_create": request.user.role in CREATE,
    })


@role_required(*CREATE)
def request_create(request):
    form = MaintenanceRequestForm(request.POST or None, request.FILES or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        req = form.save(commit=False)
        req.reported_by = request.user
        req.save()
        notify_property_people(req.unit.property, f"New maintenance request {req.ticket}",
                               f"{req.title} - unit {req.unit.number} (priority {req.get_priority_display()})",
                               Notification.Kind.MAINTENANCE)
        messages.success(request, f"Request {req.ticket} submitted.")
        return redirect("maintenance:detail", req.pk)
    return render(request, "form.html", {"form": form, "title": "Report a maintenance issue"})


@role_required(*ALL)
def request_detail(request, pk):
    req = get_object_or_404(maintenance_for(request.user).select_related("unit__building__property"), pk=pk)
    can_update = request.user.role in UPDATE
    update_form = MaintenanceUpdateForm(instance=req, user=request.user) if can_update else None
    if request.method == "POST" and can_update and "update" in request.POST:
        old_status = req.status
        update_form = MaintenanceUpdateForm(request.POST, instance=req, user=request.user)
        if update_form.is_valid():
            req = update_form.save(commit=False)
            if req.assigned_to_id and req.status == MaintenanceRequest.Status.SUBMITTED:
                req.status = MaintenanceRequest.Status.ASSIGNED
            if req.status == MaintenanceRequest.Status.COMPLETED and not req.completed_at:
                req.completed_at = timezone.now()
            req.save()
            if req.status != old_status:
                _status_notice(req)
            if "assigned_to" in update_form.changed_data and req.assigned_to:
                notify_user(req.assigned_to, f"Assigned: {req.ticket}", f"{req.title} at unit {req.unit.number}",
                            Notification.Kind.MAINTENANCE, email=True, sms=True)
            messages.success(request, "Request updated.")
            return redirect("maintenance:detail", req.pk)
    return render(request, "maintenance/request_detail.html", {
        "req": req, "update_form": update_form, "comment_form": MaintenanceCommentForm(),
        "comments": req.comments.select_related("author"),
        "flow": MaintenanceRequest.FLOW,
    })


def _status_notice(req):
    if req.reported_by:
        notify_user(req.reported_by, "Maintenance update",
                    f"Your request {req.ticket} ({req.title}) is now: {req.get_status_display()}.",
                    Notification.Kind.MAINTENANCE, email=True, sms=req.status == MaintenanceRequest.Status.COMPLETED)


@require_POST
@role_required(*ALL)
def request_comment(request, pk):
    req = get_object_or_404(maintenance_for(request.user), pk=pk)
    form = MaintenanceCommentForm(request.POST, request.FILES)
    if form.is_valid():
        comment = form.save(commit=False)
        comment.request = req
        comment.author = request.user
        comment.save()
    return redirect("maintenance:detail", req.pk)
