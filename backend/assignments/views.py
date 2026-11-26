import datetime

from django.db import transaction
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Role
from accounts.permissions import IsWorker, IsBusiness
from assignments.models import (
    Assignment, AssignmentStatus, AttendanceRecord, AttendanceStatus,
    CompletionRecord, CompletionStatus,
)
from assignments.serializers import (
    AssignmentSerializer, AttendanceRecordSerializer, AttendanceSubmitSerializer,
    CompletionRecordSerializer, CompletionSubmitSerializer,
)
from jobs.models import JobApplication, ApplicationStatus, JobListingStatus
from yawmiyati.money import format_money


class AssignmentListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = AssignmentSerializer

    def get_queryset(self):
        user = self.request.user
        if user.role == Role.WORKER:
            return Assignment.objects.filter(worker=user).select_related("job__business", "worker")
        elif user.role == Role.BUSINESS:
            return Assignment.objects.filter(job__business__user=user).select_related("job__business", "worker")
        elif user.role == Role.ADMIN:
            return Assignment.objects.all().select_related("job__business", "worker")
        return Assignment.objects.none()


class AssignmentDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = AssignmentSerializer

    def get_queryset(self):
        user = self.request.user
        if user.role == Role.WORKER:
            return Assignment.objects.filter(worker=user)
        elif user.role == Role.BUSINESS:
            return Assignment.objects.filter(job__business__user=user)
        elif user.role == Role.ADMIN:
            return Assignment.objects.all()
        return Assignment.objects.none()

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        _auto_confirm_pending(instance)
        instance.refresh_from_db()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)


class AssignmentAcceptView(APIView):
    permission_classes = [IsWorker]

    @transaction.atomic
    def post(self, request, pk):
        try:
            assignment = Assignment.objects.select_for_update().get(pk=pk, worker=request.user)
        except Assignment.DoesNotExist:
            return Response({"detail": "غير موجود."}, status=status.HTTP_404_NOT_FOUND)

        if assignment.status != AssignmentStatus.OFFERED:
            return Response(
                {"detail": f"لا يمكن قبول مهمة حالتها «{assignment.get_status_display()}»."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        snapshot = assignment.job.material_terms_snapshot()
        assignment.terms_snapshot = snapshot
        assignment.status = AssignmentStatus.ACCEPTED
        assignment.accepted_at = timezone.now()
        assignment.save(update_fields=["terms_snapshot", "status", "accepted_at"])

        application = assignment.application
        application.status = ApplicationStatus.ACCEPTED
        application.save(update_fields=["status"])

        job = assignment.job
        if job.status == JobListingStatus.PUBLISHED:
            job.status = JobListingStatus.FILLED
            job.save(update_fields=["status"])

        return Response(AssignmentSerializer(assignment).data)


class AssignmentDeclineView(APIView):
    permission_classes = [IsWorker]

    def post(self, request, pk):
        try:
            assignment = Assignment.objects.get(pk=pk, worker=request.user)
        except Assignment.DoesNotExist:
            return Response({"detail": "غير موجود."}, status=status.HTTP_404_NOT_FOUND)

        if assignment.status != AssignmentStatus.OFFERED:
            return Response(
                {"detail": f"لا يمكن رفض مهمة حالتها «{assignment.get_status_display()}»."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        assignment.status = AssignmentStatus.DECLINED
        assignment.save(update_fields=["status"])

        application = assignment.application
        application.status = ApplicationStatus.REJECTED
        application.save(update_fields=["status"])

        return Response(AssignmentSerializer(assignment).data)


class AssignmentCancelView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        user = request.user
        if user.role == Role.BUSINESS:
            qs = Assignment.objects.select_related("job").filter(pk=pk, job__business__user=user)
        elif user.role == Role.WORKER:
            qs = Assignment.objects.select_related("job").filter(pk=pk, worker=user)
        elif user.role == Role.ADMIN:
            qs = Assignment.objects.select_related("job").filter(pk=pk)
        else:
            return Response({"detail": "ليس لديك صلاحية للقيام بهذا الإجراء."}, status=status.HTTP_403_FORBIDDEN)

        try:
            assignment = qs.get()
        except Assignment.DoesNotExist:
            return Response({"detail": "غير موجود."}, status=status.HTTP_404_NOT_FOUND)

        if assignment.status in (AssignmentStatus.COMPLETED, AssignmentStatus.CANCELLED):
            return Response({"detail": "لا يمكن إلغاء مهمة مكتملة أو ملغاة مسبقاً."}, status=status.HTTP_400_BAD_REQUEST)

        if timezone.now().date() >= assignment.job.work_date:
            return Response({"detail": "لا يمكن إلغاء المهمة بعد يوم العمل."}, status=status.HTTP_400_BAD_REQUEST)

        reason = request.data.get("reason", "").strip()
        if not reason:
            return Response({"detail": "يجب ذكر السبب."}, status=status.HTTP_400_BAD_REQUEST)

        assignment.status = AssignmentStatus.CANCELLED
        assignment.cancelled_at = timezone.now()
        assignment.cancellation_reason = reason
        assignment.save(update_fields=["status", "cancelled_at", "cancellation_reason"])

        if user.role == Role.BUSINESS:
            _notify(
                assignment.worker, "ASSIGNMENT_CANCELLED",
                f"تم إلغاء مهمتك: {assignment.job.title}",
                f"أُلغيت المهمة في {assignment.job.work_date}. السبب: {reason[:100]}",
                "Assignment", str(assignment.pk),
            )
        elif user.role == Role.WORKER:
            business_user = assignment.job.business.user
            _notify(
                business_user, "ASSIGNMENT_CANCELLED",
                f"ألغى العامل مهمته: {assignment.job.title}",
                f"ألغى العامل مشاركته في {assignment.job.work_date}. السبب: {reason[:100]}",
                "Assignment", str(assignment.pk),
            )

        return Response(AssignmentSerializer(assignment).data)


class AttendanceListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        assignment = self._get_assignment(request, pk)
        if assignment is None:
            return Response({"detail": "غير موجود."}, status=status.HTTP_404_NOT_FOUND)
        _auto_confirm_pending(assignment)
        records = AttendanceRecord.objects.filter(assignment=assignment)
        return Response(AttendanceRecordSerializer(records, many=True).data)

    def post(self, request, pk):
        assignment = self._get_assignment(request, pk)
        if assignment is None:
            return Response({"detail": "غير موجود."}, status=status.HTTP_404_NOT_FOUND)

        if assignment.status not in (AssignmentStatus.ACCEPTED, AssignmentStatus.ACTIVE):
            return Response({"detail": "يمكن تسجيل الحضور للمهام المقبولة أو النشطة فقط."}, status=status.HTTP_400_BAD_REQUEST)

        serializer = AttendanceSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record = serializer.save(assignment=assignment, submitted_by=request.user)

        worker = assignment.worker
        biz_user = assignment.job.business.user
        if request.user == worker:
            _notify(
                biz_user, "ATTENDANCE_SUBMITTED",
                f"تم تسجيل الحضور: {assignment.job.title}",
                f"سجّل العامل حضوره ليوم {record.work_date}. بانتظار تأكيدك خلال 24 ساعة.",
                "Assignment", str(assignment.pk),
            )
        else:
            _notify(
                worker, "ATTENDANCE_SUBMITTED",
                f"تم تسجيل الحضور: {assignment.job.title}",
                f"سجّل صاحب العمل حضورك ليوم {record.work_date}. بانتظار تأكيدك خلال 24 ساعة.",
                "Assignment", str(assignment.pk),
            )

        return Response(AttendanceRecordSerializer(record).data, status=status.HTTP_201_CREATED)

    def _get_assignment(self, request, pk):
        user = request.user
        try:
            if user.role == Role.WORKER:
                return Assignment.objects.get(pk=pk, worker=user)
            elif user.role == Role.BUSINESS:
                return Assignment.objects.get(pk=pk, job__business__user=user)
            elif user.role == Role.ADMIN:
                return Assignment.objects.get(pk=pk)
        except Assignment.DoesNotExist:
            return None


class AttendanceConfirmView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk, rec_id):
        record, assignment = self._get_record_and_check_authority(request, pk, rec_id)
        if record is None:
            return Response({"detail": "غير موجود."}, status=status.HTTP_404_NOT_FOUND)

        if record.status != AttendanceStatus.SUBMITTED:
            return Response({"detail": "يمكن تأكيد الحضور الذي بانتظار التأكيد فقط."}, status=status.HTTP_400_BAD_REQUEST)

        record.status = AttendanceStatus.CONFIRMED
        record.confirmed_by = request.user
        record.confirmed_at = timezone.now()
        record.save(update_fields=["status", "confirmed_by", "confirmed_at"])
        return Response(AttendanceRecordSerializer(record).data)

    def _get_record_and_check_authority(self, request, pk, rec_id):
        user = request.user
        try:
            if user.role == Role.WORKER:
                assignment = Assignment.objects.get(pk=pk, worker=user)
                record = AttendanceRecord.objects.get(pk=rec_id, assignment=assignment)
                if record.submitted_by == user:
                    return None, None
            elif user.role == Role.BUSINESS:
                assignment = Assignment.objects.get(pk=pk, job__business__user=user)
                record = AttendanceRecord.objects.get(pk=rec_id, assignment=assignment)
                if record.submitted_by == user:
                    return None, None
            elif user.role == Role.ADMIN:
                assignment = Assignment.objects.get(pk=pk)
                record = AttendanceRecord.objects.get(pk=rec_id, assignment=assignment)
            else:
                return None, None
            return record, assignment
        except (Assignment.DoesNotExist, AttendanceRecord.DoesNotExist):
            return None, None


class AttendanceDisputeView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk, rec_id):
        user = request.user
        try:
            if user.role == Role.WORKER:
                assignment = Assignment.objects.get(pk=pk, worker=user)
            elif user.role == Role.BUSINESS:
                assignment = Assignment.objects.get(pk=pk, job__business__user=user)
            else:
                return Response({"detail": "ليس لديك صلاحية للقيام بهذا الإجراء."}, status=status.HTTP_403_FORBIDDEN)
            record = AttendanceRecord.objects.get(pk=rec_id, assignment=assignment)
        except (Assignment.DoesNotExist, AttendanceRecord.DoesNotExist):
            return Response({"detail": "غير موجود."}, status=status.HTTP_404_NOT_FOUND)

        if record.submitted_by == user:
            return Response(
                {"detail": "لا يمكن الاعتراض على سجل قدّمته بنفسك."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if record.status != AttendanceStatus.SUBMITTED:
            return Response({"detail": "يمكن الاعتراض على الحضور الذي بانتظار التأكيد فقط."}, status=status.HTTP_400_BAD_REQUEST)

        record.status = AttendanceStatus.DISPUTED
        record.save(update_fields=["status"])

        worker = assignment.worker
        biz_user = assignment.job.business.user
        if user == worker:
            _notify(
                biz_user, "ATTENDANCE_DISPUTED",
                f"اعتُرض على سجل الحضور: {assignment.job.title}",
                f"اعترض العامل على سجل حضور يوم {record.work_date}.",
                "Assignment", str(assignment.pk),
            )
        else:
            _notify(
                worker, "ATTENDANCE_DISPUTED",
                f"اعتُرض على حضورك: {assignment.job.title}",
                f"اعترض صاحب العمل على سجل حضورك ليوم {record.work_date}.",
                "Assignment", str(assignment.pk),
            )

        return Response(AttendanceRecordSerializer(record).data)


class CompletionView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        assignment = self._get_assignment(request, pk)
        if assignment is None:
            return Response({"detail": "غير موجود."}, status=status.HTTP_404_NOT_FOUND)
        _auto_confirm_pending(assignment)
        try:
            record = assignment.completion_record
            return Response(CompletionRecordSerializer(record).data)
        except CompletionRecord.DoesNotExist:
            return Response({"detail": "لم يُسجَّل إتمام العمل بعد."}, status=status.HTTP_404_NOT_FOUND)

    @transaction.atomic
    def post(self, request, pk):
        """The worker's «أتممت يوم عملي واطلب أجري» (or the business recording completion).
        Idempotent for the same user; refused before the work date (Gaza time)."""
        if request.user.role == Role.ADMIN:
            return Response({"detail": "ليس لديك صلاحية للقيام بهذا الإجراء."}, status=status.HTTP_403_FORBIDDEN)
        assignment = self._get_assignment(request, pk)
        if assignment is None:
            return Response({"detail": "غير موجود."}, status=status.HTTP_404_NOT_FOUND)
        assignment = Assignment.objects.select_for_update().select_related("job__business__user", "worker").get(pk=assignment.pk)

        existing = CompletionRecord.objects.filter(assignment=assignment).first()
        if existing is not None:
            if existing.submitted_by_id == request.user.pk:
                # Second press: nothing changes, no second notification.
                return Response(CompletionRecordSerializer(existing).data)
            return Response({"detail": "تم تسجيل إتمام العمل لهذه المهمة مسبقاً."}, status=status.HTTP_409_CONFLICT)

        if assignment.status not in (AssignmentStatus.ACCEPTED, AssignmentStatus.ACTIVE):
            return Response({"detail": "يمكن تسجيل إتمام العمل للمهام المقبولة أو النشطة فقط."}, status=status.HTTP_400_BAD_REQUEST)

        if timezone.localdate() < assignment.job.work_date:
            return Response({"detail": "لا يمكن طلب الأجر قبل يوم العمل."}, status=status.HTTP_400_BAD_REQUEST)

        serializer = CompletionSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record = serializer.save(assignment=assignment, submitted_by=request.user)

        assignment.status = AssignmentStatus.ACTIVE
        assignment.save(update_fields=["status"])

        worker = assignment.worker
        biz_user = assignment.job.business.user
        if request.user == worker:
            amount = format_money(assignment.terms_snapshot.get("wage_amount", assignment.job.wage_amount))
            _notify(
                biz_user, "COMPLETION_SUBMITTED",
                f"العامل يطلب أجره: {assignment.job.title}",
                f"أتمّ العامل يوم العمل ويطلب أجره {amount}. اختر «تأكيد ودفع الأجر» أو «لم يتم العمل». "
                "إن لم ترد خلال ٢٤ ساعة يتأكد الإتمام تلقائيًا.",
                "Assignment", str(assignment.pk),
            )
        else:
            _notify(
                worker, "COMPLETION_SUBMITTED",
                f"طلب إنهاء العمل: {assignment.job.title}",
                "قدّم صاحب العمل سجل الإتمام. بانتظار تأكيدك خلال 24 ساعة.",
                "Assignment", str(assignment.pk),
            )
        _audit(request.user, "completion_submitted", "CompletionRecord", record.pk, {"by": request.user.role})
        return Response(CompletionRecordSerializer(record).data, status=status.HTTP_201_CREATED)

    def _get_assignment(self, request, pk):
        user = request.user
        try:
            if user.role == Role.WORKER:
                return Assignment.objects.get(pk=pk, worker=user)
            elif user.role == Role.BUSINESS:
                return Assignment.objects.get(pk=pk, job__business__user=user)
            elif user.role == Role.ADMIN:
                return Assignment.objects.get(pk=pk)
        except Assignment.DoesNotExist:
            return None


class CompletionConfirmView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def patch(self, request, pk):
        user = request.user
        try:
            if user.role == Role.WORKER:
                assignment = Assignment.objects.get(pk=pk, worker=user)
            elif user.role == Role.BUSINESS:
                assignment = Assignment.objects.get(pk=pk, job__business__user=user)
            else:
                # Only the other party confirms; admins see it but settle through disputes.
                return Response({"detail": "ليس لديك صلاحية للقيام بهذا الإجراء."}, status=status.HTTP_403_FORBIDDEN)
            record = assignment.completion_record
        except (Assignment.DoesNotExist, CompletionRecord.DoesNotExist):
            return Response({"detail": "غير موجود."}, status=status.HTTP_404_NOT_FOUND)

        if record.status != CompletionStatus.SUBMITTED:
            return Response({"detail": "يمكن تأكيد الإتمام الذي بانتظار التأكيد فقط."}, status=status.HTTP_400_BAD_REQUEST)

        if record.submitted_by == user:
            return Response({"detail": "لا يمكنك تأكيد إتمام سجّلته أنت."}, status=status.HTTP_400_BAD_REQUEST)

        record.status = CompletionStatus.CONFIRMED
        record.confirmed_by = user
        record.confirmed_at = timezone.now()
        record.save(update_fields=["status", "confirmed_by", "confirmed_at"])

        assignment.status = AssignmentStatus.COMPLETED
        assignment.save(update_fields=["status"])

        _create_wage_obligation(assignment)
        _audit(user, "completion_confirmed", "CompletionRecord", record.pk, {"by": user.role})

        _notify(
            assignment.worker, "COMPLETION_CONFIRMED",
            f"تم تأكيد إنهاء العمل: {assignment.job.title}",
            "تم تأكيد إنهاء العمل. سيتم معالجة أجرك قريباً.",
            "Assignment", str(assignment.pk),
        )

        return Response(CompletionRecordSerializer(record).data)


# «لم يتم العمل» reasons a business can give for a worker's wage request.
BUSINESS_COMPLETION_DISPUTE_CATEGORIES = ("WORKER_NO_SHOW", "WORK_INCOMPLETE")


class CompletionDisputeView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def patch(self, request, pk):
        user = request.user
        try:
            if user.role == Role.WORKER:
                assignment = Assignment.objects.get(pk=pk, worker=user)
            elif user.role == Role.BUSINESS:
                assignment = Assignment.objects.get(pk=pk, job__business__user=user)
            else:
                return Response({"detail": "ليس لديك صلاحية للقيام بهذا الإجراء."}, status=status.HTTP_403_FORBIDDEN)
            record = assignment.completion_record
        except (Assignment.DoesNotExist, CompletionRecord.DoesNotExist):
            return Response({"detail": "غير موجود."}, status=status.HTTP_404_NOT_FOUND)

        if record.submitted_by == user:
            return Response(
                {"detail": "لا يمكن الاعتراض على سجل قدّمته بنفسك."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if record.status != CompletionStatus.SUBMITTED:
            return Response({"detail": "يمكن الاعتراض على الإتمام الذي بانتظار التأكيد فقط."}, status=status.HTTP_400_BAD_REQUEST)

        category = None
        if user.role == Role.BUSINESS:
            # «لم يتم العمل»: the reason is required and goes to the admin as a dispute.
            category = request.data.get("category")
            if category not in BUSINESS_COMPLETION_DISPUTE_CATEGORIES:
                return Response(
                    {"detail": "اختر السبب: العامل لم يحضر أو العمل لم يكتمل."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        record.status = CompletionStatus.DISPUTED
        record.save(update_fields=["status"])

        if category is not None:
            from disputes.models import Dispute, DisputeEvent
            description = (request.data.get("description") or "").strip()
            dispute = Dispute.objects.create(
                category=category,
                assignment=assignment,
                raised_by=user,
                description=description or "أبلغ صاحب العمل أن العمل لم يتم.",
            )
            DisputeEvent.objects.create(dispute=dispute, actor=user, action="opened", notes=description[:500])
        _audit(user, "completion_disputed", "CompletionRecord", record.pk, {"by": user.role, "category": category})

        worker = assignment.worker
        biz_user = assignment.job.business.user
        if user == worker:
            _notify(
                biz_user, "COMPLETION_DISPUTED",
                f"اعتُرض على إنهاء العمل: {assignment.job.title}",
                "اعترض العامل على سجل الإتمام. تواصل مع الدعم.",
                "Assignment", str(assignment.pk),
            )
        else:
            _notify(
                worker, "COMPLETION_DISPUTED",
                f"اعتُرض على إنهاء العمل: {assignment.job.title}",
                "اعترض صاحب العمل على طلب إنهاء العمل. تواصل مع الدعم.",
                "Assignment", str(assignment.pk),
            )

        return Response(CompletionRecordSerializer(record).data)


class BusinessCompleteAssignmentView(APIView):
    """«تأكيد ودفع الأجر» / «تأكيد إتمام العمل»: the business confirms the work. The wage
    becomes DUE and is paid on the «تحويل الأجر» screen (wages/<id>/payment/)."""
    permission_classes = [IsBusiness]

    @transaction.atomic
    def post(self, request, pk):
        try:
            assignment = Assignment.objects.select_for_update().get(
                pk=pk, job__business__user=request.user
            )
        except Assignment.DoesNotExist:
            return Response({"detail": "غير موجود."}, status=status.HTTP_404_NOT_FOUND)

        if assignment.status == AssignmentStatus.COMPLETED:
            return Response(AssignmentSerializer(assignment).data)

        if assignment.status not in (AssignmentStatus.ACCEPTED, AssignmentStatus.ACTIVE):
            return Response(
                {"detail": "يمكن تأكيد إتمام المهام المقبولة والنشطة فقط."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if timezone.localdate() < assignment.job.work_date:
            return Response(
                {"detail": "لا يمكن تأكيد الإتمام قبل يوم العمل."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        now = timezone.now()
        record = CompletionRecord.objects.select_for_update().filter(assignment=assignment).first()
        if record is None:
            # The worker did not press «أتممت يوم عملي»; the business records it.
            record = CompletionRecord.objects.create(
                assignment=assignment,
                submitted_by=request.user,
                status=CompletionStatus.CONFIRMED,
                confirmed_by=request.user,
                confirmed_at=now,
            )
        elif record.status == CompletionStatus.SUBMITTED:
            # «تأكيد ودفع الأجر» on the worker's request.
            record.status = CompletionStatus.CONFIRMED
            record.confirmed_by = request.user
            record.confirmed_at = now
            record.save(update_fields=["status", "confirmed_by", "confirmed_at"])
        elif record.status == CompletionStatus.DISPUTED:
            return Response(
                {"detail": "يوجد نزاع مفتوح على إتمام هذه المهمة، ويتابعه المشرف."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        _audit(request.user, "completion_confirmed", "CompletionRecord", record.pk, {"by": request.user.role})

        assignment.status = AssignmentStatus.COMPLETED
        assignment.save(update_fields=["status"])

        _create_wage_obligation(assignment)
        # The wage is now DUE; the business pays it on the «تحويل الأجر» screen.

        return Response(AssignmentSerializer(assignment).data)


def _audit(actor, action, model_name, object_id, details=None):
    from audit.models import AuditEvent
    AuditEvent.objects.create(
        actor=actor, action=action, model_name=model_name, object_id=str(object_id), details=details or {},
    )


def _notify(recipient, notification_type, title, body, related_model, related_id):
    try:
        from notifications.models import Notification
        Notification.objects.create(
            recipient=recipient,
            notification_type=notification_type,
            title=title,
            body=body,
            related_model=related_model,
            related_id=related_id,
        )
    except Exception:
        pass


def _create_wage_obligation(assignment):
    from django.db import IntegrityError
    from wages.models import WageObligation

    if WageObligation.objects.filter(assignment=assignment).exists():
        return

    snapshot = assignment.terms_snapshot
    wage_amount = snapshot.get("wage_amount", 0)
    wage_currency = snapshot.get("wage_currency", "ILS")

    # Wathb pays daily: the wage is due the day the work is confirmed finished.
    due_date = timezone.localdate()

    from wages.models import WageObligationStatus
    try:
        # The amount comes only from the agreed terms, in integer agorot.
        with transaction.atomic():  # savepoint: callers are often inside a transaction
            obligation = WageObligation.objects.create(
                assignment=assignment,
                amount=int(wage_amount),
                currency=wage_currency,
                due_date=due_date,
                status=WageObligationStatus.DUE,
            )
    except IntegrityError:
        return
    _audit(None, "wage_created", "WageObligation", obligation.pk,
           {"amount": obligation.amount, "assignment_id": str(assignment.pk)})


def _auto_confirm_pending(assignment):
    from audit.models import AuditEvent
    now = timezone.now()
    cutoff = now - datetime.timedelta(hours=24)

    for record in list(AttendanceRecord.objects.filter(
        assignment=assignment,
        status=AttendanceStatus.SUBMITTED,
        submitted_at__lte=cutoff,
    )):
        with transaction.atomic():
            r = AttendanceRecord.objects.select_for_update().get(pk=record.pk)
            if r.status != AttendanceStatus.SUBMITTED:
                continue
            r.status = AttendanceStatus.CONFIRMED
            r.confirmed_at = now
            r.save(update_fields=["status", "confirmed_at"])
            worker = assignment.worker
            biz_user = assignment.job.business.user
            title = f"تم التأكيد التلقائي: حضور {assignment.job.title} ليوم {r.work_date}"
            body = "لم يُستجب خلال 24 ساعة، تم التأكيد تلقائياً."
            _notify(worker, "ATTENDANCE_AUTO_CONFIRMED", title, body, "Assignment", str(assignment.pk))
            _notify(biz_user, "ATTENDANCE_AUTO_CONFIRMED", title, body, "Assignment", str(assignment.pk))
            AuditEvent.objects.create(
                actor=None,
                action="attendance_auto_confirmed",
                model_name="AttendanceRecord",
                object_id=str(r.pk),
            )

    comp = CompletionRecord.objects.filter(
        assignment=assignment,
        status=CompletionStatus.SUBMITTED,
        submitted_at__lte=cutoff,
    ).first()
    if comp is None:
        return
    with transaction.atomic():
        c = CompletionRecord.objects.select_for_update().get(pk=comp.pk)
        if c.status != CompletionStatus.SUBMITTED:
            return
        c.status = CompletionStatus.CONFIRMED
        c.confirmed_at = now
        c.save(update_fields=["status", "confirmed_at"])
        assignment.status = AssignmentStatus.COMPLETED
        assignment.save(update_fields=["status"])
        _create_wage_obligation(assignment)
        worker = assignment.worker
        biz_user = assignment.job.business.user
        title = f"تم التأكيد التلقائي: إتمام {assignment.job.title}"
        body = "لم يُستجب خلال 24 ساعة، تم تأكيد إتمام المهمة تلقائياً."
        _notify(worker, "COMPLETION_AUTO_CONFIRMED", title, body, "Assignment", str(assignment.pk))
        _notify(biz_user, "COMPLETION_AUTO_CONFIRMED", title, body, "Assignment", str(assignment.pk))
        AuditEvent.objects.create(
            actor=None,
            action="completion_auto_confirmed",
            model_name="CompletionRecord",
            object_id=str(c.pk),
        )
