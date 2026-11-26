from rest_framework import serializers
from disputes.models import Dispute, DisputeEvent


class DisputeEventSerializer(serializers.ModelSerializer):
    actor_phone = serializers.CharField(source="actor.phone", read_only=True)

    class Meta:
        model = DisputeEvent
        fields = ["id", "actor_phone", "action", "notes", "timestamp"]
        read_only_fields = fields


class DisputeSerializer(serializers.ModelSerializer):
    raised_by_phone = serializers.CharField(source="raised_by.phone", read_only=True)
    assigned_to_phone = serializers.CharField(source="assigned_to.phone", read_only=True, default=None)
    wage_obligation_status = serializers.CharField(source="wage_obligation.status", read_only=True, default=None)
    disputed_declaration = serializers.SerializerMethodField()

    class Meta:
        model = Dispute
        fields = [
            "id", "category", "assignment", "wage_obligation", "wage_obligation_status",
            "disputed_declaration", "raised_by_phone", "description", "status",
            "assigned_to_phone", "created_at", "resolved_at", "resolution_notes",
        ]
        read_only_fields = [
            "id", "wage_obligation_status", "disputed_declaration", "raised_by_phone", "status",
            "assigned_to_phone", "created_at", "resolved_at", "resolution_notes",
        ]

    def get_disputed_declaration(self, obj):
        """The declaration an admin settles with verify/reject, if the wage is still disputed."""
        from wages.models import PaymentDeclarationStatus

        if obj.wage_obligation_id is None:
            return None
        pk = obj.wage_obligation.declarations.filter(
            status=PaymentDeclarationStatus.DISPUTED
        ).order_by("-declared_at").values_list("pk", flat=True).first()
        return str(pk) if pk else None


class DisputeCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Dispute
        fields = ["category", "assignment", "wage_obligation", "description"]

    def validate(self, attrs):
        user = self.context["request"].user
        assignment = attrs["assignment"]
        if assignment.worker != user and assignment.job.business.user != user:
            raise serializers.ValidationError("لست طرفاً في هذه المهمة.")
        return attrs
