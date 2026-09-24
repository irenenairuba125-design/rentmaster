from django.urls import path

from . import views

app_name = "billing"
urlpatterns = [
    path("invoices/", views.invoice_list, name="invoice_list"),
    path("invoices/generate/", views.invoice_generate, name="invoice_generate"),
    path("invoices/<int:pk>/", views.invoice_detail, name="invoice_detail"),
    path("invoices/<int:pk>/items/", views.invoice_item_add, name="invoice_item_add"),
    path("invoices/<int:pk>/cancel/", views.invoice_cancel, name="invoice_cancel"),
    path("invoices/<int:pk>/record-payment/", views.payment_record, name="payment_record"),
    path("invoices/<int:pk>/pay/", views.invoice_pay, name="invoice_pay"),
    path("payments/", views.payment_list, name="payment_list"),
    path("payments/<int:pk>/", views.payment_detail, name="payment_detail"),
    path("payments/<int:pk>/check/", views.payment_check, name="payment_check"),
    path("payments/<int:pk>/verify/", views.payment_verify, name="payment_verify"),
    path("payments/<int:pk>/reject/", views.payment_reject, name="payment_reject"),
    path("payments/callback/<str:provider>/<str:reference>/", views.payment_callback, name="payment_callback"),
    path("receipts/<int:pk>/", views.receipt_detail, name="receipt_detail"),
    path("receipts/verify/<uuid:code>/", views.receipt_verify, name="receipt_verify"),
    path("arrears/", views.arrears, name="arrears"),
    path("utilities/", views.utility_list, name="utility_list"),
    path("utilities/last/<int:unit_pk>/", views.last_reading, name="last_reading"),
]
