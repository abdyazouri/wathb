"""«تحويل الأجر»: the business pays the worker's wage.

Money moves only from the business's Jawwal Pay wallet to the worker's wallet; Wathb
never receives, holds or forwards funds. Every write locks the wage (and the attempt)
inside transaction.atomic(). The one-time code is relayed once to the provider and is
never stored, logged, audited or echoed back.
"""
import datetime
import re

from django.db import transaction
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsBusiness
from wages.models import (
    OPEN_ATTEMPT_STATUSES, PaymentAttempt, PaymentAttemptStatus, PaymentDeclaration, PaymentMethod,
    WageObligation, WageObligationStatus,
)
from wages.payments import AUTOMATIC, get_provider, payment_mode
from wages.payments.base import PaymentError, ProviderTimeout, TransferRequest, TransferStatus
from yawmiyati.money import format_money

PAYABLE = (WageObligationStatus.PENDING, WageObligationStatus.DUE, WageObligationStatus.REJECTED)
RESEND_AFTER = datetime.timedelta(seconds=60)
CODE_FORMAT = re.compile(r"\d{4,8}")

ERRORS = {
    PaymentError.WRONG_CODE: "الرمز غير صحيح. تأكد منه وحاول مرة أخرى.",
    PaymentError.CODE_EXPIRED: "انتهت صلاحية الرمز. اطلب رمزًا جديدًا.",
    PaymentError.INSUFFICIENT_BALANCE: "رصيد محفظتك في Jawwal Pay لا يكفي لتحويل الأجر.",
    PaymentError.RECIPIENT_NO_WALLET: "لا توجد محفظة Jawwal Pay على رقم العامل. ادفع له يدويًا أو تواصل مع الدعم.",
}
TIMEOUT_DETAIL = "لم يصل رد من Jawwal Pay. سنتحقق من حالة التحويل قبل أي محاولة جديدة."


def _audit(actor, action, attempt_or_obligation, details=None):
    from audit.models import AuditEvent
    AuditEvent.objects.create(
        actor=actor, action=action, model_name=type(attempt_or_obligation).__name__,
        object_id=str(attempt_or_obligation.pk), details=details or {},
    )


def _lock_wage(request, pk):
    """The wage of a job owned by this business, locked. None → 404."""
    try:
        return WageObligation.objects.select_for_update(of=("self",)).select_related(
            "assignment__worker__worker_profile", "assignment__job__business",
        ).get(pk=pk, assignment__job__business__user=request.user)
    except WageObligation.DoesNotExist:
        return None


def _open_attempt(obligation):
    return PaymentAttempt.objects.select_for_update().filter(
        wage_obligation=obligation, status__in=OPEN_ATTEMPT_STATUSES
    ).first()


def _finalize_paid(obligation, attempt, reference):
    """The provider confirmed the transfer: record it and tell the worker."""
    now = timezone.now()
    attempt.status = PaymentAttemptStatus.SUCCEEDED
    attempt.provider_reference = reference or attempt.provider_reference
    attempt.completed_at = now
    attempt.save(update_fields=["status", "provider_reference", "completed_at"])
    declaration = PaymentDeclaration.objects.create(
        wage_obligation=obligation,
        declared_amount=attempt.amount,
        currency=attempt.currency,
        payment_date=timezone.localdate(),
        payment_method=PaymentMethod.JAWWAL_PAY,
        transaction_reference=attempt.provider_reference,
        declared_by=attempt.initiated_by,
        provider_confirmed=True,
    )
    obligation.status = WageObligationStatus.AWAITING_ACK
    obligation.save(update_fields=["status"])
    _audit(attempt.initiated_by, "payment_succeeded", attempt,
           {"amount": attempt.amount, "reference": attempt.provider_reference, "declaration_id": str(declaration.pk)})
    from notifications.models import Notification
    amount = format_money(attempt.amount)
    Notification.objects.create(
        recipient=obligation.assignment.worker,
        notification_type="PAYMENT_DECLARED",
        title=f"وصلك أجرك: {amount}",
        body=f"حُوِّل أجرك {amount} إلى محفظتك في Jawwal Pay. إن لم يصلك اضغط «لم أستلم أجري» خلال ٢٤ ساعة.",
        related_model="WageObligation",
        related_id=str(obligation.pk),
    )


def _reconcile(obligation, attempt, provider):
    """After a timeout: ask the provider before anything else. Returns the attempt's new status."""
    try:
        result = provider.get_status(attempt.idempotency_key, attempt.provider_reference or None)
    except ProviderTimeout:
        return attempt.status
    if result.state == TransferStatus.SUCCEEDED:
        _finalize_paid(obligation, attempt, result.reference)
    elif result.state == TransferStatus.FAILED:
        attempt.status = PaymentAttemptStatus.FAILED
        attempt.failure_code = result.failure or "FAILED"
        attempt.completed_at = timezone.now()
        attempt.save(update_fields=["status", "failure_code", "completed_at"])
    elif result.state == TransferStatus.PENDING_CODE:
        attempt.status = PaymentAttemptStatus.INITIATED
        attempt.save(update_fields=["status"])
    _audit(None, "payment_reconciled", attempt, {"provider_state": result.state})
    return attempt.status


def _payment_info(obligation, attempt=None):
    worker = obligation.assignment.worker
    try:
        worker_name = worker.worker_profile.full_name
    except Exception:
        worker_name = ""
    wallet = obligation.assignment.job.business.jawwal_pay_wallet
    mode = payment_mode()
    attempt = attempt or PaymentAttempt.objects.filter(wage_obligation=obligation).first()
    return {
        "wage_id": str(obligation.pk),
        "mode": mode,
        "status": obligation.status,
        "payable": obligation.status in PAYABLE,
        "amount": obligation.amount,
        "amount_display": format_money(obligation.amount),
        "job_title": obligation.assignment.job.title,
        "worker_name": worker_name,
        "worker_wallet": worker.phone,          # the worker's wallet is the registered phone
        "business_wallet": wallet or None,
        "needs_wallet": mode == AUTOMATIC and not wallet,
        "attempt": None if attempt is None else {
            "status": attempt.status,
            "failure": attempt.failure_code or None,
            "resend_available_at": (attempt.code_sent_at + RESEND_AFTER).isoformat() if attempt.code_sent_at else None,
        },
    }


class PaymentInfoView(APIView):
    """GET wages/<pk>/payment/ — everything the «تحويل الأجر» screen shows, read-only."""
    permission_classes = [IsBusiness]

    @transaction.atomic
    def get(self, request, pk):
        obligation = _lock_wage(request, pk)
        if obligation is None:
            return Response({"detail": "غير موجود."}, status=status.HTTP_404_NOT_FOUND)
        attempt = _open_attempt(obligation)
        if attempt is not None and attempt.status == PaymentAttemptStatus.UNKNOWN and payment_mode() == AUTOMATIC:
            _reconcile(obligation, attempt, get_provider())
        return Response(_payment_info(obligation))


class PaymentInitiateView(APIView):
    """POST wages/<pk>/payment/initiate/ — «إرسال»: start the transfer (or re-send the code)."""
    permission_classes = [IsBusiness]

    @transaction.atomic
    def post(self, request, pk):
        obligation = _lock_wage(request, pk)
        if obligation is None:
            return Response({"detail": "غير موجود."}, status=status.HTTP_404_NOT_FOUND)
        if payment_mode() != AUTOMATIC:
            return Response({"detail": "التحويل الآلي غير مفعّل. حوّل من تطبيق Jawwal Pay ثم اضغط «حوّلت الأجر»."},
                            status=status.HTTP_400_BAD_REQUEST)
        provider = get_provider()

        attempt = _open_attempt(obligation)
        if attempt is not None and attempt.status == PaymentAttemptStatus.UNKNOWN:
            # A previous attempt timed out: never start another before knowing what happened.
            if _reconcile(obligation, attempt, provider) == PaymentAttemptStatus.UNKNOWN:
                return Response({"detail": "ما زلنا نتحقق من التحويل السابق. حاول بعد قليل."},
                                status=status.HTTP_409_CONFLICT)
            obligation.refresh_from_db()
            attempt = _open_attempt(obligation)

        if obligation.status not in PAYABLE:
            return Response({"detail": "تم تحويل هذا الأجر.", **_payment_info(obligation)}, status=status.HTTP_409_CONFLICT)
        if PaymentAttempt.objects.filter(wage_obligation=obligation, status=PaymentAttemptStatus.SUCCEEDED).exists():
            # Paid automatically before and later rejected by the admin: never transfer twice.
            return Response({"detail": "حُوِّل هذا الأجر آليًا من قبل. راجع مشرف وَثْب."}, status=status.HTTP_409_CONFLICT)

        business = obligation.assignment.job.business
        if not business.jawwal_pay_wallet:
            return Response({"detail": "اربط محفظة Jawwal Pay في ملف المنشأة أولًا.", "needs_wallet": True},
                            status=status.HTTP_400_BAD_REQUEST)

        now = timezone.now()
        if attempt is not None:  # INITIATED: re-send the code, same transfer
            if attempt.code_sent_at and now < attempt.code_sent_at + RESEND_AFTER:
                wait = int((attempt.code_sent_at + RESEND_AFTER - now).total_seconds()) + 1
                return Response({"detail": f"يمكنك طلب رمز جديد بعد {wait} ثانية.", "retry_after": wait},
                                status=status.HTTP_429_TOO_MANY_REQUESTS)
            action = "payment_code_resent"
        else:
            sequence = PaymentAttempt.objects.filter(wage_obligation=obligation).count() + 1
            attempt = PaymentAttempt.objects.create(
                wage_obligation=obligation,
                provider=provider.name,
                idempotency_key=f"wathb-wage-{obligation.pk}-{sequence}",
                amount=obligation.amount,          # the agreed terms, never the client
                currency=obligation.currency,
                payer_wallet=business.jawwal_pay_wallet,
                payee_wallet=obligation.assignment.worker.phone,
                initiated_by=request.user,
            )
            action = "payment_initiated"

        transfer = TransferRequest(
            idempotency_key=attempt.idempotency_key, amount=attempt.amount, currency=attempt.currency,
            payer_wallet=attempt.payer_wallet, payee_wallet=attempt.payee_wallet,
        )
        try:
            reference = provider.initiate(transfer)
        except PaymentError as e:
            attempt.status = PaymentAttemptStatus.FAILED
            attempt.failure_code = e.code
            attempt.completed_at = now
            attempt.save(update_fields=["status", "failure_code", "completed_at"])
            _audit(request.user, "payment_failed", attempt, {"failure": e.code, "step": "initiate"})
            return Response({"detail": ERRORS.get(e.code, "تعذّر بدء التحويل."), "failure": e.code},
                            status=status.HTTP_400_BAD_REQUEST)
        except ProviderTimeout:
            attempt.status = PaymentAttemptStatus.UNKNOWN
            attempt.save(update_fields=["status"])
            _audit(request.user, "payment_timeout", attempt, {"step": "initiate"})
            return Response({"detail": TIMEOUT_DETAIL}, status=status.HTTP_504_GATEWAY_TIMEOUT)

        attempt.provider_reference = reference
        attempt.code_sent_at = now
        attempt.save(update_fields=["provider_reference", "code_sent_at"])
        _audit(request.user, action, attempt, {"amount": attempt.amount})
        return Response(_payment_info(obligation, attempt))


@method_decorator(sensitive_post_parameters("code"), name="dispatch")
class PaymentConfirmView(APIView):
    """POST wages/<pk>/payment/confirm/ {"code"} — relay the SMS code once. Never stored."""
    permission_classes = [IsBusiness]

    @sensitive_variables("code")
    @transaction.atomic
    def post(self, request, pk):
        code = str(request.data.get("code") or "").strip()
        obligation = _lock_wage(request, pk)
        if obligation is None:
            return Response({"detail": "غير موجود."}, status=status.HTTP_404_NOT_FOUND)
        if not CODE_FORMAT.fullmatch(code):
            return Response({"detail": "أدخل الرمز كما وصلك في الرسالة."}, status=status.HTTP_400_BAD_REQUEST)

        attempt = _open_attempt(obligation)
        if attempt is None or attempt.status != PaymentAttemptStatus.INITIATED:
            if obligation.status not in PAYABLE:
                # Double tap after success: same answer, nothing moves.
                return Response(_payment_info(obligation))
            if attempt is not None:  # UNKNOWN
                return Response({"detail": "ما زلنا نتحقق من التحويل السابق. حاول بعد قليل."},
                                status=status.HTTP_409_CONFLICT)
            return Response({"detail": "لا يوجد تحويل بانتظار الرمز. اضغط «إرسال» أولًا."},
                            status=status.HTTP_400_BAD_REQUEST)

        provider = get_provider()
        try:
            reference = provider.confirm(attempt.provider_reference, code)
        except PaymentError as e:
            if e.code in (PaymentError.INSUFFICIENT_BALANCE, PaymentError.RECIPIENT_NO_WALLET):
                attempt.status = PaymentAttemptStatus.FAILED
                attempt.failure_code = e.code
                attempt.completed_at = timezone.now()
                attempt.save(update_fields=["status", "failure_code", "completed_at"])
            _audit(request.user, "payment_failed" if attempt.status == PaymentAttemptStatus.FAILED
                   else "payment_code_rejected", attempt, {"failure": e.code, "step": "confirm"})
            return Response({"detail": ERRORS.get(e.code, "تعذّر إتمام التحويل."), "failure": e.code},
                            status=status.HTTP_400_BAD_REQUEST)
        except ProviderTimeout:
            attempt.status = PaymentAttemptStatus.UNKNOWN
            attempt.save(update_fields=["status"])
            _audit(request.user, "payment_timeout", attempt, {"step": "confirm"})
            return Response({"detail": TIMEOUT_DETAIL}, status=status.HTTP_504_GATEWAY_TIMEOUT)

        _finalize_paid(obligation, attempt, reference)
        return Response(_payment_info(obligation, attempt))
