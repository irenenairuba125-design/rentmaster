from django.urls import path

from . import views

app_name = "finance"
urlpatterns = [
    path("expenses/", views.expense_list, name="expense_list"),
    path("reports/", views.financial_report, name="report"),
]
