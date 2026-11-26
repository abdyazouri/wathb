from django.urls import path
from wages.payment_views import PaymentConfirmView, PaymentInfoView, PaymentInitiateView
from wages.views import (
    WageObligationListView, WageObligationDetailView,
    DeclarePaymentView, AcknowledgePaymentView, DisputePaymentView,
    UploadEvidenceView, EvidenceFileView, AdminVerifyPaymentView,
    AdminPhoneResolveView,
)

urlpatterns = [
    path("", WageObligationListView.as_view(), name="wage-list"),
    path("<uuid:pk>/", WageObligationDetailView.as_view(), name="wage-detail"),
    path("<uuid:pk>/declare-payment/", DeclarePaymentView.as_view(), name="wage-declare-payment"),
    path("<uuid:pk>/acknowledge/", AcknowledgePaymentView.as_view(), name="wage-acknowledge"),
    path("<uuid:pk>/dispute-payment/", DisputePaymentView.as_view(), name="wage-dispute-payment"),
    path("<uuid:pk>/declarations/<uuid:dec_id>/evidence/", UploadEvidenceView.as_view(), name="wage-upload-evidence"),
    path("<uuid:pk>/declarations/<uuid:dec_id>/evidence/<uuid:ev_id>/file/", EvidenceFileView.as_view(), name="wage-evidence-file"),
    path("<uuid:pk>/declarations/<uuid:dec_id>/verify/", AdminVerifyPaymentView.as_view(), name="wage-admin-verify"),
    path("<uuid:pk>/admin-phone-resolve/", AdminPhoneResolveView.as_view(), name="wage-admin-phone-resolve"),
    # «تحويل الأجر»
    path("<uuid:pk>/payment/", PaymentInfoView.as_view(), name="wage-payment"),
    path("<uuid:pk>/payment/initiate/", PaymentInitiateView.as_view(), name="wage-payment-initiate"),
    path("<uuid:pk>/payment/confirm/", PaymentConfirmView.as_view(), name="wage-payment-confirm"),
]
