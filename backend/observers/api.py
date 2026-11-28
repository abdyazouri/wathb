"""Admin API for observer accounts (the Render free plan has no Shell and admins are not Django staff).

POST   admin/observers/            create; the response carries the one-time set-password link, once
GET    admin/observers/            list (no links)
PATCH  admin/observers/<id>/       extend (expires_at), deactivate/activate (is_active), change level
POST   admin/observers/<id>/link/  a new one-time set-password link

ADMIN role only. Every action goes to the audit log; links never do.
"""
from django.db import transaction
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import BusinessProfile
from accounts.permissions import IsAdminRole
from audit.models import AuditEvent
from observers.audit import client_ip
from observers.models import ObserverLanguage, ObserverLevel, ObserverProfile
from observers.services import create_observer
from observers.tokens import set_password_link


def _audit(request, action, profile, **details):
    AuditEvent.objects.create(actor=request.user, action=action, model_name="ObserverProfile",
                              object_id=str(profile.pk), details=details, ip_address=client_ip(request))


class ObserverSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source="user.email", read_only=True)
    is_active = serializers.BooleanField(source="user.is_active", read_only=True)
    usable = serializers.BooleanField(source="is_usable", read_only=True)
    all_businesses = serializers.BooleanField(source="scope.all_businesses", read_only=True)
    business_ids = serializers.SerializerMethodField()
    start_date = serializers.DateField(source="scope.start_date", read_only=True)
    end_date = serializers.DateField(source="scope.end_date", read_only=True)

    class Meta:
        model = ObserverProfile
        fields = ["id", "display_name", "organisation", "email", "level", "language", "expires_at", "is_active",
                  "usable", "all_businesses", "business_ids", "start_date", "end_date", "created_at"]

    def get_business_ids(self, obj):
        return [] if obj.scope.all_businesses else sorted(obj.scope.businesses.values_list("pk", flat=True))


class ObserverCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    organisation = serializers.CharField(max_length=200)
    email = serializers.EmailField()
    level = serializers.ChoiceField(choices=ObserverLevel.choices)
    language = serializers.ChoiceField(choices=ObserverLanguage.choices, default=ObserverLanguage.ARABIC)
    expires_at = serializers.DateField()
    business_ids = serializers.ListField(child=serializers.IntegerField(), required=False, default=list,
                                         help_text="Empty: all businesses.")
    start_date = serializers.DateField(required=False, allow_null=True)
    end_date = serializers.DateField(required=False, allow_null=True)

    def validate_business_ids(self, ids):
        missing = set(ids) - set(BusinessProfile.objects.filter(pk__in=ids).values_list("pk", flat=True))
        if missing:
            raise serializers.ValidationError(f"منشآت غير موجودة: {sorted(missing)}")
        return ids

    def validate(self, attrs):
        start, end = attrs.get("start_date"), attrs.get("end_date")
        if start and end and end < start:
            raise serializers.ValidationError({"end_date": "تاريخ النهاية قبل تاريخ البداية."})
        return attrs


class ObserverUpdateSerializer(serializers.Serializer):
    expires_at = serializers.DateField(required=False)
    is_active = serializers.BooleanField(required=False)
    level = serializers.ChoiceField(choices=ObserverLevel.choices, required=False)


class ObserverListCreateView(APIView):
    permission_classes = [IsAdminRole]

    def get(self, request):
        profiles = ObserverProfile.objects.select_related("user", "scope").order_by("-created_at")
        return Response(ObserverSerializer(profiles, many=True).data)

    def post(self, request):
        s = ObserverCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        try:
            profile, link = create_observer(
                name=d["name"], organisation=d["organisation"], email=d["email"], level=d["level"],
                language=d["language"], expires_at=d["expires_at"], business_ids=d["business_ids"] or None,
                start_date=d.get("start_date"), end_date=d.get("end_date"), created_by=request.user,
            )
        except ValueError:
            return Response({"detail": "يوجد حساب بهذا البريد الإلكتروني."}, status=status.HTTP_409_CONFLICT)
        _audit(request, "observer_created", profile, level=profile.level, language=profile.language,
               expires_at=str(profile.expires_at), all_businesses=profile.scope.all_businesses)
        # The link is returned this once and is never stored or logged.
        return Response({"observer": ObserverSerializer(profile).data, "set_password_link": link,
                         "link_valid_hours": 48}, status=status.HTTP_201_CREATED)


class ObserverDetailView(APIView):
    permission_classes = [IsAdminRole]

    def patch(self, request, pk):
        try:
            profile = ObserverProfile.objects.select_related("user", "scope").get(pk=pk)
        except ObserverProfile.DoesNotExist:
            return Response({"detail": "غير موجود."}, status=status.HTTP_404_NOT_FOUND)
        s = ObserverUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        if not d:
            return Response({"detail": "لا يوجد ما يُعدَّل."}, status=status.HTTP_400_BAD_REQUEST)
        changes = {}
        with transaction.atomic():
            if "expires_at" in d:
                changes["expires_at"] = [str(profile.expires_at), str(d["expires_at"])]
                profile.expires_at = d["expires_at"]
            if "level" in d:
                changes["level"] = [profile.level, d["level"]]
                profile.level = d["level"]
            profile.save()
            if "is_active" in d:
                changes["is_active"] = [profile.user.is_active, d["is_active"]]
                profile.user.is_active = d["is_active"]  # inactive: signed out on the next request
                profile.user.save(update_fields=["is_active"])
        _audit(request, "observer_updated", profile, changes=changes)
        return Response(ObserverSerializer(profile).data)


class ObserverLinkView(APIView):
    permission_classes = [IsAdminRole]

    def post(self, request, pk):
        try:
            profile = ObserverProfile.objects.select_related("user").get(pk=pk)
        except ObserverProfile.DoesNotExist:
            return Response({"detail": "غير موجود."}, status=status.HTTP_404_NOT_FOUND)
        _audit(request, "observer_link_issued", profile)
        return Response({"set_password_link": set_password_link(profile.user), "link_valid_hours": 48})
