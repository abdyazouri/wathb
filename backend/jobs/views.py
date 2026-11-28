from django.db import transaction
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Role
from accounts.permissions import IsAdminRole, IsWorker, IsBusiness, IsVerifiedBusiness
from jobs.models import PaymentMethod, JobListing, JobApplication, JobListingStatus, ApplicationStatus, JobCategory
from jobs.serializers import (
    JobListingSerializer,
    JobListingCreateSerializer,
    JobApplicationSerializer,
)


class JobListView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = JobListingSerializer

    def get_queryset(self):
        user = self.request.user
        if user.role == Role.WORKER:
            qs = JobListing.objects.filter(status=JobListingStatus.PUBLISHED).select_related("business")
        elif user.role == Role.BUSINESS:
            qs = JobListing.objects.filter(business__user=user).select_related("business")
        elif user.role == Role.ADMIN:
            qs = JobListing.objects.all().select_related("business")
        else:
            qs = JobListing.objects.none()

        city = self.request.query_params.get("city")
        if city:
            qs = qs.filter(location_city__icontains=city)
        date = self.request.query_params.get("work_date")
        if date:
            qs = qs.filter(work_date=date)
        category = self.request.query_params.get("category")
        if category:
            qs = qs.filter(category=category)
        return qs

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsVerifiedBusiness()]
        return [IsAuthenticated()]

    def create(self, request, *args, **kwargs):
        # Validate with the write serializer, respond with the full read serializer
        # so the client receives id, status, and all computed fields.
        write_ser = JobListingCreateSerializer(data=request.data)
        write_ser.is_valid(raise_exception=True)
        instance = write_ser.save(business=request.user.business_profile)
        return Response(JobListingSerializer(instance).data, status=status.HTTP_201_CREATED)


class JobDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = JobListingSerializer

    def get_queryset(self):
        user = self.request.user
        if user.role == Role.BUSINESS:
            return JobListing.objects.filter(business__user=user)
        if user.role == Role.ADMIN:
            return JobListing.objects.all()
        return JobListing.objects.filter(status=JobListingStatus.PUBLISHED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        write_ser = JobListingCreateSerializer(instance, data=request.data, partial=partial)
        write_ser.is_valid(raise_exception=True)
        instance = write_ser.save(version=instance.version + 1)
        return Response(JobListingSerializer(instance).data)

    def perform_destroy(self, instance):
        if instance.status != JobListingStatus.DRAFT:
            from rest_framework.exceptions import ValidationError
            raise ValidationError("يمكن حذف المسودات فقط.")
        instance.delete()


class JobSubmitView(APIView):
    """Move a DRAFT listing to PENDING_REVIEW for publishing."""
    permission_classes = [IsVerifiedBusiness]

    def post(self, request, pk):
        try:
            job = JobListing.objects.get(pk=pk, business__user=request.user)
        except JobListing.DoesNotExist:
            return Response({"detail": "غير موجود."}, status=status.HTTP_404_NOT_FOUND)

        if not job.can_transition_to(JobListingStatus.PENDING_REVIEW):
            return Response(
                {"detail": f"لا يمكن إرسال وظيفة حالتها «{job.get_status_display()}» للمراجعة."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        job.status = JobListingStatus.PENDING_REVIEW
        job.save(update_fields=["status"])
        return Response(JobListingSerializer(job).data)


class JobPublishView(APIView):
    permission_classes = [IsVerifiedBusiness]

    def post(self, request, pk):
        try:
            job = JobListing.objects.get(pk=pk, business__user=request.user)
        except JobListing.DoesNotExist:
            return Response({"detail": "غير موجود."}, status=status.HTTP_404_NOT_FOUND)

        if not job.can_transition_to(JobListingStatus.PUBLISHED):
            return Response(
                {"detail": f"لا يمكن نشر وظيفة حالتها «{job.get_status_display()}»."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if job.is_funded:
            from funding.models import FundingAllocation
            has_allocation = FundingAllocation.objects.filter(
                job_listing=job, status__in=["RESERVED", "ALLOCATED"]
            ).exists()
            if not has_allocation:
                return Response(
                    {"detail": "الوظيفة الممولة تحتاج تخصيص تمويل معتمد قبل النشر."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        job.status = JobListingStatus.PUBLISHED
        job.published_at = timezone.now()
        job.save(update_fields=["status", "published_at"])
        return Response(JobListingSerializer(job).data)


def _admin_audit(request, action, job, **details):
    from audit.models import AuditEvent
    AuditEvent.objects.create(actor=request.user, action=action, model_name="JobListing", object_id=str(job.pk),
                              details=details, ip_address=request.META.get("REMOTE_ADDR"))


def _notify_business(job, notification_type, title, body):
    """In-app notification to the business; opens the job's applicants in the app."""
    from notifications.models import Notification
    Notification.objects.create(recipient=job.business.user, notification_type=notification_type, title=title,
                                body=body, related_model="JobListing", related_id=str(job.pk))


class AdminBusinessJobsView(APIView):
    """admin/businesses/<profile id>/jobs/ — the business's jobs (GET), or a new job on its behalf (POST).

    POST uses exactly the business's own create rules: a verified, active business and the same
    JobListingCreateSerializer validation. The job is a draft; publishing goes through
    admin/jobs/<id>/publish/. Audited, and the business is notified in the app.
    """
    permission_classes = [IsAdminRole]

    def _business(self, pk):
        from accounts.models import BusinessProfile
        try:
            return BusinessProfile.objects.select_related("user").get(pk=pk)
        except BusinessProfile.DoesNotExist:
            return None

    def get(self, request, pk):
        business = self._business(pk)
        if business is None:
            return Response({"detail": "غير موجود."}, status=status.HTTP_404_NOT_FOUND)
        jobs = JobListing.objects.filter(business=business).select_related("business").order_by("-created_at")
        return Response(JobListingSerializer(jobs, many=True).data)

    @transaction.atomic
    def post(self, request, pk):
        from accounts.models import VerificationStatus
        from notifications.models import NotificationType

        business = self._business(pk)
        if business is None:
            return Response({"detail": "غير موجود."}, status=status.HTTP_404_NOT_FOUND)
        # Same gate as IsVerifiedBusiness on the business's own create.
        if business.verification_status != VerificationStatus.APPROVED or not business.user.is_active:
            return Response({"detail": "المنشأة غير موثّقة أو حسابها غير مفعّل، فلا يمكن إضافة وظائف لها."},
                            status=status.HTTP_403_FORBIDDEN)
        write_ser = JobListingCreateSerializer(data=request.data)
        write_ser.is_valid(raise_exception=True)
        job = write_ser.save(business=business)  # status DRAFT (model default)
        _admin_audit(request, "job_created_by_admin", job, on_behalf_of_business=business.pk,
                     note=f"created by admin on behalf of business {business.pk}")
        _notify_business(job, NotificationType.JOB_CREATED_BY_ADMIN, f"أضاف مشرف وَثْب وظيفة باسمك: {job.title}",
                         f"وظيفة يوم {job.work_date} محفوظة كمسودة في «وظائفي». راجعها، وتُنشر بموافقتك.")
        return Response(JobListingSerializer(job).data, status=status.HTTP_201_CREATED)


class AdminJobPublishView(APIView):
    """POST admin/jobs/<id>/publish/ {"expected_version": n, "reason": "..."} — an admin publishes a job on
    behalf of its business (the owner cannot press «نشر الوظيفة» themselves).

    Same rules as the business's own publish: a verified, active business, a DRAFT or PENDING_REVIEW job,
    and approved funding for a funded job. expected_version must match, so only the terms the admin
    confirmed with the business are published. The audit log records who published it and for whom.
    """
    permission_classes = [IsAdminRole]

    @transaction.atomic
    def post(self, request, pk):
        from accounts.models import VerificationStatus

        try:
            job = JobListing.objects.select_for_update().select_related("business__user").get(pk=pk)
        except JobListing.DoesNotExist:
            return Response({"detail": "غير موجود."}, status=status.HTTP_404_NOT_FOUND)
        expected = request.data.get("expected_version")
        if expected is None or str(expected) != str(job.version):
            return Response(
                {"detail": "تغيّرت شروط الوظيفة أو لم تُحدَّد نسختها. راجع الشروط من جديد قبل النشر.",
                 "version": job.version},
                status=status.HTTP_409_CONFLICT,
            )
        business = job.business
        if business.verification_status != VerificationStatus.APPROVED:
            return Response({"detail": "المنشأة غير موثّقة، فلا يمكن نشر وظائفها."}, status=status.HTTP_400_BAD_REQUEST)
        if not business.user.is_active:
            return Response({"detail": "حساب المنشأة غير مفعّل."}, status=status.HTTP_400_BAD_REQUEST)
        if job.status not in (JobListingStatus.DRAFT, JobListingStatus.PENDING_REVIEW):
            return Response({"detail": f"لا يمكن نشر وظيفة حالتها «{job.get_status_display()}»."},
                            status=status.HTTP_400_BAD_REQUEST)
        if job.is_funded:
            from funding.models import FundingAllocation
            if not FundingAllocation.objects.filter(job_listing=job, status__in=["RESERVED", "ALLOCATED"]).exists():
                return Response({"detail": "الوظيفة الممولة تحتاج تخصيص تمويل معتمد قبل النشر."},
                                status=status.HTTP_400_BAD_REQUEST)

        previous = job.status
        # The same path as the business's own button: DRAFT → PENDING_REVIEW → PUBLISHED.
        if job.status == JobListingStatus.DRAFT:
            job.status = JobListingStatus.PENDING_REVIEW
        job.status = JobListingStatus.PUBLISHED
        job.published_at = timezone.now()
        job.save(update_fields=["status", "published_at"])
        _admin_audit(request, "job_published_by_admin", job, on_behalf_of_business=business.pk,
                     previous_status=previous, version=job.version, reason=str(request.data.get("reason", ""))[:300])
        from notifications.models import NotificationType
        _notify_business(job, NotificationType.JOB_PUBLISHED_BY_ADMIN, f"نشر مشرف وَثْب وظيفتك: {job.title}",
                         f"وظيفة يوم {job.work_date} منشورة الآن ويراها العمال. تابع المتقدمين من «وظائفي».")
        return Response(JobListingSerializer(job).data)


class JobCancelView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        user = request.user
        if user.role == Role.BUSINESS:
            qs = JobListing.objects.filter(pk=pk, business__user=user)
        elif user.role == Role.ADMIN:
            qs = JobListing.objects.filter(pk=pk)
        else:
            return Response({"detail": "ليس لديك صلاحية للقيام بهذا الإجراء."}, status=status.HTTP_403_FORBIDDEN)

        try:
            job = qs.get()
        except JobListing.DoesNotExist:
            return Response({"detail": "غير موجود."}, status=status.HTTP_404_NOT_FOUND)

        if not job.can_transition_to(JobListingStatus.CANCELLED):
            return Response(
                {"detail": f"لا يمكن إلغاء وظيفة حالتها «{job.get_status_display()}»."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        reason = request.data.get("reason", "").strip()
        if not reason:
            return Response({"detail": "يجب ذكر السبب."}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            job.status = JobListingStatus.CANCELLED
            job.cancellation_reason = reason
            job.save(update_fields=["status", "cancellation_reason"])

            # Capture workers to notify before bulk update changes statuses.
            workers_to_notify = list(
                job.applications
                .filter(status__in=[ApplicationStatus.PENDING, ApplicationStatus.OFFERED])
                .select_related("worker")
                .values_list("worker", flat=True)
            )

            # Cancel pending/offered applications.
            job.applications.filter(
                status__in=[ApplicationStatus.PENDING, ApplicationStatus.OFFERED]
            ).update(status=ApplicationStatus.CANCELLED)

            # Cancel accepted assignments (work hasn't started yet).
            from assignments.models import Assignment, AssignmentStatus
            Assignment.objects.filter(
                job=job,
                status__in=[AssignmentStatus.OFFERED, AssignmentStatus.ACCEPTED]
            ).update(status=AssignmentStatus.CANCELLED)

            # Notify affected workers.
            from accounts.models import User as AccountUser
            for worker in AccountUser.objects.filter(pk__in=workers_to_notify):
                _notify_worker(worker, "JOB_CANCELLED", job)

        return Response(JobListingSerializer(job).data)


class JobCloneView(APIView):
    """Clone an existing job listing as a new DRAFT owned by the same business."""
    permission_classes = [IsVerifiedBusiness]

    def post(self, request, pk):
        try:
            original = JobListing.objects.get(pk=pk, business__user=request.user)
        except JobListing.DoesNotExist:
            return Response({"detail": "غير موجود."}, status=status.HTTP_404_NOT_FOUND)

        clone = JobListing(
            business=original.business,
            title=original.title,
            description=original.description,
            location_address=original.location_address,
            location_city=original.location_city,
            work_date=original.work_date,
            start_time=original.start_time,
            end_time=original.end_time,
            num_workers_needed=original.num_workers_needed,
            wage_amount=original.wage_amount,
            wage_currency=original.wage_currency,
            wage_basis=original.wage_basis,
            payment_method=PaymentMethod.JAWWAL_PAY,  # new jobs: Jawwal Pay only
            required_skills=original.required_skills,
            attendance_requirements=original.attendance_requirements,
            cancellation_policy=original.cancellation_policy,
            additional_conditions=original.additional_conditions,
            is_funded=original.is_funded,
            status=JobListingStatus.DRAFT,
        )
        clone.save()
        return Response(JobListingSerializer(clone).data, status=status.HTTP_201_CREATED)


class JobCategoryListView(APIView):
    """Public-ish list of job categories (no auth required — workers see chips before login)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response([
            {"value": value, "label": label}
            for value, label in JobCategory.choices
        ])


class JobApplicationListView(generics.ListAPIView):
    permission_classes = [IsBusiness]
    serializer_class = JobApplicationSerializer

    def get_queryset(self):
        from django.db.models import Count, Q
        from django.utils import timezone
        try:
            job = JobListing.objects.get(pk=self.kwargs["pk"], business__user=self.request.user)
        except JobListing.DoesNotExist:
            return JobApplication.objects.none()
        month_start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return (
            JobApplication.objects
            .filter(job=job)
            .select_related("worker", "worker__worker_profile")
            .annotate(
                attended_this_month=Count(
                    "worker__assignments__attendance_records",
                    filter=Q(
                        worker__assignments__attendance_records__status="CONFIRMED",
                        worker__assignments__attendance_records__work_date__gte=month_start.date(),
                    ),
                    distinct=True,
                )
            )
            .order_by("attended_this_month", "applied_at")
        )


class WorkerApplicationListView(generics.ListAPIView):
    """Worker's own applications across all jobs."""
    permission_classes = [IsWorker]
    serializer_class = JobApplicationSerializer

    def get_queryset(self):
        return (
            JobApplication.objects
            .filter(worker=self.request.user)
            .select_related("worker", "job")
            .order_by("-applied_at")
        )


class JobApplyView(APIView):
    permission_classes = [IsWorker]

    def post(self, request, pk):
        try:
            job = JobListing.objects.get(pk=pk, status=JobListingStatus.PUBLISHED)
        except JobListing.DoesNotExist:
            return Response({"detail": "الوظيفة غير موجودة أو غير متاحة."}, status=status.HTTP_404_NOT_FOUND)

        if JobApplication.objects.filter(job=job, worker=request.user).exists():
            return Response({"detail": "لقد تقدّمت لهذه الوظيفة مسبقاً."}, status=status.HTTP_409_CONFLICT)

        app = JobApplication.objects.create(
            job=job,
            worker=request.user,
            cover_note=request.data.get("cover_note", ""),
            terms_at_apply=job.material_terms_snapshot(),
        )
        return Response(JobApplicationSerializer(app).data, status=status.HTTP_201_CREATED)


class ApplicationActionView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk, app_id):
        user = request.user

        if user.role == Role.BUSINESS:
            try:
                job = JobListing.objects.get(pk=pk, business__user=user)
                app = JobApplication.objects.get(pk=app_id, job=job)
            except (JobListing.DoesNotExist, JobApplication.DoesNotExist):
                return Response({"detail": "غير موجود."}, status=status.HTTP_404_NOT_FOUND)

            action_name = request.data.get("action")
            if action_name == "offer":
                if app.status != ApplicationStatus.PENDING:
                    return Response({"detail": "الطلب ليس قيد الانتظار."}, status=status.HTTP_400_BAD_REQUEST)
                with transaction.atomic():
                    app.status = ApplicationStatus.OFFERED
                    app.reviewed_at = timezone.now()
                    app.save(update_fields=["status", "reviewed_at"])
                    from assignments.models import Assignment, AssignmentStatus
                    assignment, created = Assignment.objects.get_or_create(
                        job=job,
                        worker=app.worker,
                        defaults={
                            "application": app,
                            "terms_snapshot": {},
                            "status": AssignmentStatus.OFFERED,
                        },
                    )
                    if not created:
                        assignment.status = AssignmentStatus.OFFERED
                        assignment.save(update_fields=["status"])
                _notify_worker(app.worker, "JOB_OFFER", job)
            elif action_name == "reject":
                if app.status not in (ApplicationStatus.PENDING, ApplicationStatus.OFFERED):
                    return Response({"detail": "لا يمكن الرفض في هذه المرحلة."}, status=status.HTTP_400_BAD_REQUEST)
                with transaction.atomic():
                    app.status = ApplicationStatus.REJECTED
                    app.reviewed_at = timezone.now()
                    app.save(update_fields=["status", "reviewed_at"])
                    # «سحب العرض»: the offer must not stay acceptable.
                    _close_open_offer(app, "CANCELLED", "سحب صاحب العمل العرض.")
                _notify_worker(app.worker, "APPLICATION_REJECTED", job)
            else:
                return Response({"detail": "الإجراء غير صالح. الخيارات: offer أو reject."}, status=status.HTTP_400_BAD_REQUEST)

            return Response(JobApplicationSerializer(app).data)

        elif user.role == Role.WORKER:
            try:
                app = JobApplication.objects.get(pk=app_id, job__pk=pk, worker=user)
            except JobApplication.DoesNotExist:
                return Response({"detail": "غير موجود."}, status=status.HTTP_404_NOT_FOUND)

            action_name = request.data.get("action")
            if action_name == "withdraw":
                if app.status not in (ApplicationStatus.PENDING, ApplicationStatus.OFFERED):
                    return Response({"detail": "لا يمكن سحب الطلب في هذه المرحلة."}, status=status.HTTP_400_BAD_REQUEST)
                with transaction.atomic():
                    app.status = ApplicationStatus.WITHDRAWN
                    app.save(update_fields=["status"])
                    _close_open_offer(app, "DECLINED")
                return Response(JobApplicationSerializer(app).data)
            else:
                return Response({"detail": "يمكن للعامل سحب طلبه فقط."}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"detail": "ليس لديك صلاحية للقيام بهذا الإجراء."}, status=status.HTTP_403_FORBIDDEN)

    def delete(self, request, pk, app_id):
        try:
            app = JobApplication.objects.get(pk=app_id, job__pk=pk, worker=request.user)
        except JobApplication.DoesNotExist:
            return Response({"detail": "غير موجود."}, status=status.HTTP_404_NOT_FOUND)

        if app.status not in (ApplicationStatus.PENDING,):
            return Response({"detail": "لا يمكن الحذف في هذه المرحلة."}, status=status.HTTP_400_BAD_REQUEST)
        app.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


def _close_open_offer(app, new_status, reason=""):
    """An offer still waiting for the worker ends with its application (rejected or withdrawn)."""
    from assignments.models import Assignment, AssignmentStatus
    fields = {"status": getattr(AssignmentStatus, new_status)}
    if new_status == "CANCELLED":
        fields.update(cancelled_at=timezone.now(), cancellation_reason=reason)
    Assignment.objects.filter(job=app.job, worker=app.worker, status=AssignmentStatus.OFFERED).update(**fields)


def _notify_worker(worker, notification_type, job):
    try:
        from notifications.models import Notification
        titles = {
            "JOB_OFFER": f"اختارك صاحب العمل: {job.title}",
            "APPLICATION_REJECTED": f"تم رفض طلبك: {job.title}",
            "JOB_CANCELLED": f"تم إلغاء الوظيفة: {job.title}",
        }
        bodies = {
            "JOB_OFFER": f"اختارتك {job.business.legal_name} للعمل في '{job.title}' بتاريخ {job.work_date}. راجع الشروط وأكّد حضورك من «طلباتي».",
            "APPLICATION_REJECTED": f"تم رفض طلبك للوظيفة '{job.title}'.",
            "JOB_CANCELLED": f"أُلغيت الوظيفة '{job.title}' بتاريخ {job.work_date}.",
        }
        Notification.objects.create(
            recipient=worker,
            notification_type=notification_type,
            title=titles.get(notification_type, ""),
            body=bodies.get(notification_type, ""),
            related_model="JobListing",
            related_id=str(job.id),
        )
    except Exception:
        pass
