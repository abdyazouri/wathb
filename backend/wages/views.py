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

    def post(self, request, pk):
        try:
            obligation = WageObligation.objects.get(pk=pk, assignment__worker=request.user)
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
    """Admin verifies or rejects a payment declaration."""
    permission_classes = [IsAdminRole]

    @transaction.atomic
    def post(self, request, pk, dec_id):
        try:
            obligation = WageObligation.objects.select_for_update().get(pk=pk)
            declaration = obligation.declarations.select_for_update().get(pk=dec_id)
        except (WageObligation.DoesNotExist, PaymentDeclaration.DoesNotExist):
            return Response({"detail": "غير موجود."}, status=status.HTTP_404_NOT_FOUND)

        action_name = request.data.get("action")
        review_notes = request.data.get("review_notes", "")

        if action_name == "verify":
            if declaration.status not in (
                PaymentDeclarationStatus.SUBMITTED,
                PaymentDeclarationStatus.ACKNOWLEDGED,
            ):
                return Response(
                    {"detail": f"لا يمكن التحقق من إعلان دفع حالته «{declaration.get_status_display()}»."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            declaration.status = PaymentDeclarationStatus.VERIFIED
            declaration.reviewed_by = request.user
            declaration.reviewed_at = timezone.now()
            declaration.review_notes = review_notes
            declaration.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_notes"])

            obligation.status = WageObligationStatus.VERIFIED_PAID
            obligation.save(update_fields=["status"])

            _log_audit(request.user, "payment_verified", "PaymentDeclaration", str(declaration.pk))
            _notify_worker(obligation.assignment.worker, "PAYMENT_VERIFIED", obligation)

        elif action_name == "reject":
            if not review_notes:
                return Response({"detail": "يجب كتابة ملاحظات المراجعة (review_notes) عند الرفض."}, status=status.HTTP_400_BAD_REQUEST)
            declaration.status = PaymentDeclarationStatus.REJECTED
            declaration.reviewed_by = request.user
            declaration.reviewed_at = timezone.now()
            declaration.review_notes = review_notes
            declaration.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_notes"])

            obligation.status = WageObligationStatus.REJECTED
            obligation.save(update_fields=["status"])

            _log_audit(request.user, "payment_rejected", "PaymentDeclaration", str(declaration.pk), {"notes": review_notes})
            _notify_worker(obligation.assignment.worker, "PAYMENT_REJECTED", obligation)

        else:
            return Response({"detail": "الإجراء غير صالح. الخيارات: verify أو reject."}, status=status.HTTP_400_BAD_REQUEST)

        return Response(PaymentDeclarationSerializer(declaration).data)


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
            "PAYMENT_VERIFIED": "تم التحقق من دفع أجرك",
            "PAYMENT_REJECTED": "تم رفض إعلان الدفع",
        }
        bodies = {
            "PAYMENT_DECLARED": f"أعلن صاحب العمل عن دفع {amount}. الرجاء تأكيد الاستلام.",
            "PAYMENT_VERIFIED": f"تم التحقق من دفع {amount}.",
            "PAYMENT_REJECTED": f"رفض المسؤول إعلان دفع {amount}. سيتواصل معك.",
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

        with transaction.atomic():
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
