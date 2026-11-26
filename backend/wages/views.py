import datetime
from django.db import transaction
from django.http import FileResponse
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.conf import settings

from yawmiyati.money import format_money, to_arabic_indic

from accounts.models import Role
from accounts.permissions import IsWorker, IsBusiness, IsAdminRole
from wages.models import (
    WageObligation, WageObligationStatus,
    PaymentDeclaration, PaymentDeclarationStatus,
    PaymentEvidence,
)
from wages.serializers import (
    WageObligationSerializer, PaymentDeclarationSerializer,
    PaymentDeclarationCreateSerializer, PaymentEvidenceSerializer,
)


class WageObligationListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = WageObligationSerializer

    def list(self, request, *args, **kwargs):
        _auto_confirm_all_pending()
        from notifications.views import _create_wage_reminders
        _create_wage_reminders(request.user)
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        user = self.request.user
        if user.role == Role.WORKER:
            qs = WageObligation.objects.filter(assignment__worker=user).select_related("assignment__job", "assignment__worker")
        elif user.role == Role.BUSINESS:
            qs = WageObligation.objects.filter(assignment__job__business__user=user).select_related("assignment__job", "assignment__worker")
        elif user.role == Role.ADMIN:
            qs = WageObligation.objects.all().select_related("assignment__job", "assignment__worker")
        else:
            return WageObligation.objects.none()
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs


class WageObligationDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = WageObligationSerializer

    def get_queryset(self):
        user = self.request.user
        if user.role == Role.WORKER:
            return WageObligation.objects.filter(assignment__worker=user)
        elif user.role == Role.BUSINESS:
            return WageObligation.objects.filter(assignment__job__business__user=user)
        elif user.role == Role.ADMIN:
            return WageObligation.objects.all()
        return WageObligation.objects.none()


class DeclarePaymentView(APIView):
    permission_classes = [IsBusiness]

    @transaction.atomic
    def post(self, request, pk):
        try:
            obligation = WageObligation.objects.select_for_update().get(
                pk=pk, assignment__job__business__user=request.user
            )
        except WageObligation.DoesNotExist:
            return Response({"detail": "غير موجود."}, status=status.HTTP_404_NOT_FOUND)

        if obligation.status not in (WageObligationStatus.PENDING, WageObligationStatus.DUE, WageObligationStatus.REJECTED):
            return Response(
                {"detail": f"لا يمكن الإعلان عن الدفع لأجر حالته «{obligation.get_status_display()}»."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = PaymentDeclarationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        declaration = serializer.save(
            wage_obligation=obligation,
            declared_by=request.user,
        )

        obligation.status = WageObligationStatus.AWAITING_ACK
        obligation.save(update_fields=["status"])

        _notify_worker(
            obligation.assignment.worker,
            "PAYMENT_DECLARED",
            obligation,
        )

        return Response(PaymentDeclarationSerializer(declaration).data, status=status.HTTP_201_CREATED)


class AcknowledgePaymentView(APIView):
    permission_classes = [IsWorker]

    @transaction.atomic
    def post(self, request, pk):
        try:
            obligation = WageObligation.objects.select_for_update().get(
                pk=pk, assignment__worker=request.user
            )
        except WageObligation.DoesNotExist:
            return Response({"detail": "غير موجود."}, status=status.HTTP_404_NOT_FOUND)

        if obligation.status != WageObligationStatus.AWAITING_ACK:
            return Response(
                {"detail": "لا يوجد إعلان دفع بانتظار إقرارك."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        declaration = obligation.declarations.filter(
            status=PaymentDeclarationStatus.SUBMITTED
        ).order_by("-declared_at").first()

        if declaration:
            declaration.status = PaymentDeclarationStatus.ACKNOWLEDGED
            declaration.save(update_fields=["status"])

        obligation.status = WageObligationStatus.VERIFIED_PAID
        obligation.save(update_fields=["status"])

        _log_audit(request.user, "payment_acknowledged", "WageObligation", str(obligation.pk))
        return Response(WageObligationSerializer(obligation).data)


class DisputePaymentView(APIView):
    permission_classes = [IsWorker]

    @transaction.atomic
    def post(self, request, pk):
        try:
            obligation = WageObligation.objects.select_for_update().get(pk=pk, assignment__worker=request.user)
        except WageObligation.DoesNotExist:
            return Response({"detail": "غير موجود."}, status=status.HTTP_404_NOT_FOUND)

        if obligation.status != WageObligationStatus.AWAITING_ACK:
            return Response(
                {"detail": "لا يوجد ما يمكن الاعتراض عليه في هذه المرحلة."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        declaration = obligation.declarations.filter(
            status=PaymentDeclarationStatus.SUBMITTED
        ).order_by("-declared_at").first()
        if declaration:
            declaration.status = PaymentDeclarationStatus.DISPUTED
            declaration.save(update_fields=["status"])

        obligation.status = WageObligationStatus.DISPUTED
        obligation.save(update_fields=["status"])

        category = request.data.get("category", "PAYMENT_NOT_RECEIVED")
        description = request.data.get("description", "")
        _create_dispute(
            raised_by=request.user,
            assignment=obligation.assignment,
            wage_obligation=obligation,
            category=category,
            description=description,
        )

        return Response(WageObligationSerializer(obligation).data)


class UploadEvidenceView(APIView):
    permission_classes = [IsBusiness]

    def post(self, request, pk, dec_id):
        try:
            obligation = WageObligation.objects.get(pk=pk, assignment__job__business__user=request.user)
            declaration = obligation.declarations.get(pk=dec_id)
        except (WageObligation.DoesNotExist, PaymentDeclaration.DoesNotExist):
            return Response({"detail": "غير موجود."}, status=status.HTTP_404_NOT_FOUND)

        uploaded_file = request.FILES.get("file")
        if not uploaded_file:
            return Response({"detail": "لم يتم إرفاق ملف."}, status=status.HTTP_400_BAD_REQUEST)

        if uploaded_file.size > settings.MAX_UPLOAD_SIZE_BYTES:
            return Response(
                {"detail": f"حجم الملف يتجاوز الحد المسموح ({to_arabic_indic(settings.MAX_UPLOAD_SIZE_BYTES // 1024 // 1024)} ميغابايت)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        file_bytes = uploaded_file.read(2048)
        uploaded_file.seek(0)
        try:
            import magic as _magic
            detected_type = _magic.from_buffer(file_bytes, mime=True)
        except Exception:
            detected_type = _detect_mime_from_bytes(file_bytes)

        if detected_type not in settings.ALLOWED_UPLOAD_CONTENT_TYPES:
            return Response(
                {"detail": "نوع الملف غير مسموح. الأنواع المسموحة: صورة JPEG أو PNG أو ملف PDF."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        evidence = PaymentEvidence.objects.create(
            declaration=declaration,
            file=uploaded_file,
            original_filename=uploaded_file.name[:255],
            content_type=detected_type,
            file_size=uploaded_file.size,
            uploaded_by=request.user,
        )
        return Response(PaymentEvidenceSerializer(evidence).data, status=status.HTTP_201_CREATED)


class EvidenceFileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk, dec_id, ev_id):
        user = request.user
        try:
            obligation = WageObligation.objects.get(pk=pk)
            declaration = obligation.declarations.get(pk=dec_id)
            evidence = declaration.evidence_files.get(pk=ev_id)
        except (WageObligation.DoesNotExist, PaymentDeclaration.DoesNotExist, PaymentEvidence.DoesNotExist):
            return Response({"detail": "غير موجود."}, status=status.HTTP_404_NOT_FOUND)

        if user.role == Role.WORKER and obligation.assignment.worker != user:
            return Response({"detail": "ليس لديك صلاحية للقيام بهذا الإجراء."}, status=status.HTTP_403_FORBIDDEN)
        elif user.role == Role.BUSINESS and obligation.assignment.job.business.user != user:
            return Response({"detail": "ليس لديك صلاحية للقيام بهذا الإجراء."}, status=status.HTTP_403_FORBIDDEN)

        return FileResponse(evidence.file.open("rb"), content_type=evidence.content_type)


class AdminVerifyPaymentView(APIView):
    """Admin settles a disputed wage: "verify" (the payment happened) or "reject"
    (it did not; the wage returns to DUE and the business must pay and declare again)."""
    permission_classes = [IsAdminRole]

    @transaction.atomic
    def post(self, request, pk, dec_id):
        try:
            obligation = WageObligation.objects.select_for_update().get(pk=pk)
            declaration = obligation.declarations.select_for_update().get(pk=dec_id)
        except (WageObligation.DoesNotExist, PaymentDeclaration.DoesNotExist):
            return Response({"detail": "غير موجود."}, status=status.HTTP_404_NOT_FOUND)

        action_name = request.data.get("action")
        if action_name not in ("verify", "reject"):
            return Response({"detail": "الإجراء غير صالح. الخيارات: verify أو reject."}, status=status.HTTP_400_BAD_REQUEST)

        # Only a dispute is settled here. While the worker can still acknowledge or
        # dispute, the worker decides (or the admin calls by phone).
        if obligation.status != WageObligationStatus.DISPUTED:
            return Response(
                {"detail": f"لا يمكن البتّ في الدفع إلا لأجر متنازع عليه. حالة الأجر «{obligation.get_status_display()}»."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if declaration.status != PaymentDeclarationStatus.DISPUTED:
            return Response(
                {"detail": f"لا يمكن البتّ في إعلان دفع حالته «{declaration.get_status_display()}»."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        review_notes = (request.data.get("review_notes") or "").strip()
        if not review_notes:
            return Response({"detail": "يجب كتابة ملاحظات المراجعة (review_notes)."}, status=status.HTTP_400_BAD_REQUEST)

        verified = action_name == "verify"
        declaration.status = PaymentDeclarationStatus.VERIFIED if verified else PaymentDeclarationStatus.REJECTED
        declaration.reviewed_by = request.user
        declaration.reviewed_at = timezone.now()
        declaration.review_notes = review_notes
        declaration.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_notes"])

        obligation.status = WageObligationStatus.VERIFIED_PAID if verified else WageObligationStatus.DUE
        obligation.save(update_fields=["status"])

        _resolve_wage_disputes(obligation, request.user, review_notes)
        _log_audit(
            request.user, "payment_verified" if verified else "payment_rejected",
            "PaymentDeclaration", str(declaration.pk), {"notes": review_notes},
        )
        _notify_settlement(obligation, verified, review_notes)

        return Response(PaymentDeclarationSerializer(declaration).data)


def _resolve_wage_disputes(obligation, admin, notes):
    """Mark the wage's open disputes RESOLVED with the admin's settlement note."""
    from disputes.models import Dispute, DisputeEvent, DisputeStatus

    now = timezone.now()
    for dispute in Dispute.objects.select_for_update().filter(
        wage_obligation=obligation, status__in=[DisputeStatus.OPEN, DisputeStatus.IN_REVIEW],
    ):
        dispute.status = DisputeStatus.RESOLVED
        dispute.resolved_at = now
        dispute.resolution_notes = notes
        dispute.save(update_fields=["status", "resolved_at", "resolution_notes"])
        DisputeEvent.objects.create(dispute=dispute, actor=admin, action="resolved", notes=notes[:500])


def _notify_settlement(obligation, verified, notes):
    from notifications.models import Notification, NotificationType

    amount = format_money(obligation.amount)
    note = f" ملاحظة المشرف: {notes[:100]}"
    if verified:
        notification_type = NotificationType.PAYMENT_VERIFIED
        messages = [
            (obligation.assignment.worker, "تم التحقق من دفع أجرك",
             f"راجع المشرف النزاع وتحقّق من دفع {amount}.{note}"),
            (obligation.assignment.job.business.user, "تم التحقق من الدفع",
             f"راجع المشرف النزاع وتحقّق من دفعك {amount} للعامل.{note}"),
        ]
    else:
        notification_type = NotificationType.PAYMENT_REJECTED
        messages = [
            (obligation.assignment.worker, "لم يثبت دفع أجرك",
             f"راجع المشرف النزاع ولم يثبت دفع {amount}. أجرك مستحق وعلى صاحب العمل أن يدفعه من جديد.{note}"),
            (obligation.assignment.job.business.user, "مطلوب دفع الأجر من جديد",
             f"راجع المشرف النزاع ولم يثبت دفع {amount}. ادفع الأجر للعامل ثم أعلن عن الدفع من جديد.{note}"),
        ]
    for recipient, title, body in messages:
        Notification.objects.create(
            recipient=recipient,
            notification_type=notification_type,
            title=title,
            body=body,
            related_model="WageObligation",
            related_id=str(obligation.pk),
        )


def _detect_mime_from_bytes(data):
    if data[:4] in (b'\xff\xd8\xff\xe0', b'\xff\xd8\xff\xe1', b'\xff\xd8\xff\xdb'):
        return "image/jpeg"
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return "image/png"
    if data[:4] == b'%PDF':
        return "application/pdf"
    return "application/octet-stream"


def _notify_worker(worker, notification_type, obligation):
    try:
        from notifications.models import Notification
        amount = format_money(obligation.amount)
        titles = {
            "PAYMENT_DECLARED": "تم الإعلان عن دفع أجرك",
        }
        bodies = {
            "PAYMENT_DECLARED": f"أعلن صاحب العمل عن دفع {amount}. الرجاء تأكيد الاستلام.",
        }
        Notification.objects.create(
            recipient=worker,
            notification_type=notification_type,
            title=titles.get(notification_type, "إشعار أجر"),
            body=bodies.get(notification_type, ""),
            related_model="WageObligation",
            related_id=str(obligation.pk),
        )
    except Exception:
        pass


class AdminStaleWageListView(APIView):
    permission_classes = [IsAdminRole]

    def get(self, request):
        cutoff = timezone.now() - datetime.timedelta(days=3)
        obligations = WageObligation.objects.filter(
            status=WageObligationStatus.AWAITING_ACK,
            declarations__status=PaymentDeclarationStatus.SUBMITTED,
            declarations__declared_at__lte=cutoff,
        ).distinct().prefetch_related("declarations").select_related(
            "assignment", "assignment__worker", "assignment__job", "assignment__job__business"
        )
        return Response(WageObligationSerializer(obligations, many=True).data)


class AdminPhoneResolveView(APIView):
    permission_classes = [IsAdminRole]

    @transaction.atomic
    def patch(self, request, pk):
        action = request.data.get("action")
        notes = (request.data.get("notes") or "").strip()

        if action not in ("confirmed_by_phone", "disputed_by_phone"):
            return Response(
                {"detail": "الإجراء غير صالح. الخيارات: confirmed_by_phone أو disputed_by_phone."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not notes:
            return Response({"detail": "يجب كتابة الملاحظات."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            obligation = WageObligation.objects.select_for_update().get(pk=pk)
        except WageObligation.DoesNotExist:
            return Response({"detail": "غير موجود."}, status=status.HTTP_404_NOT_FOUND)

        if obligation.status != WageObligationStatus.AWAITING_ACK:
            return Response(
                {"detail": "الأجر ليس بانتظار إقرار العامل."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        declaration = obligation.declarations.filter(
            status=PaymentDeclarationStatus.SUBMITTED
        ).order_by("-declared_at").first()

        if not declaration:
            return Response(
                {"detail": "لا يوجد إعلان دفع بانتظار إقرار العامل."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if action == "confirmed_by_phone":
            declaration.status = PaymentDeclarationStatus.VERIFIED
            declaration.reviewed_by = request.user
            declaration.reviewed_at = timezone.now()
            declaration.review_notes = f"[تأكيد هاتفي عبر المشرف] {notes}"
            declaration.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_notes"])
            obligation.status = WageObligationStatus.VERIFIED_PAID
            obligation.save(update_fields=["status"])
            _log_audit(
                request.user, "admin_phone_confirmed", "WageObligation",
                str(obligation.pk), {"notes": notes}
            )
        else:
            declaration.status = PaymentDeclarationStatus.DISPUTED
            declaration.reviewed_by = request.user
            declaration.reviewed_at = timezone.now()
            declaration.review_notes = f"[اعتراض هاتفي عبر المشرف] {notes}"
            declaration.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_notes"])
            obligation.status = WageObligationStatus.DISPUTED
            obligation.save(update_fields=["status"])
            _create_dispute(
                raised_by=request.user,
                assignment=obligation.assignment,
                wage_obligation=obligation,
                category="PAYMENT_NOT_RECEIVED",
                description=f"[اعتراض هاتفي عبر المشرف] {notes}",
            )
            _log_audit(
                request.user, "admin_phone_disputed", "WageObligation",
                str(obligation.pk), {"notes": notes}
            )

        return Response(WageObligationSerializer(obligation).data)


def _auto_confirm_all_pending():
    from assignments.views import _auto_confirm_pending
    from assignments.models import Assignment, AttendanceRecord, AttendanceStatus, CompletionRecord, CompletionStatus
    now = timezone.now()
    cutoff = now - datetime.timedelta(hours=24)
    pks = set()
    for pk in AttendanceRecord.objects.filter(status=AttendanceStatus.SUBMITTED, submitted_at__lte=cutoff).values_list("assignment_id", flat=True):
        pks.add(pk)
    for pk in CompletionRecord.objects.filter(status=CompletionStatus.SUBMITTED, submitted_at__lte=cutoff).values_list("assignment_id", flat=True):
        pks.add(pk)
    for assignment in Assignment.objects.filter(pk__in=pks).select_related("job__business", "worker"):
        _auto_confirm_pending(assignment)


def _log_audit(actor, action, model_name, object_id, details=None):
    try:
        from audit.models import AuditEvent
        AuditEvent.objects.create(
            actor=actor,
            action=action,
            model_name=model_name,
            object_id=object_id,
            details=details or {},
        )
    except Exception:
        pass


def _create_dispute(raised_by, assignment, wage_obligation, category, description):
    try:
        from disputes.models import Dispute
        Dispute.objects.create(
            category=category,
            assignment=assignment,
            wage_obligation=wage_obligation,
            raised_by=raised_by,
            description=description,
        )
    except Exception:
        pass
