from rest_framework import serializers
from yawmiyati.money import format_money
from wages.models import WageObligation, PaymentDeclaration, PaymentEvidence


class WageObligationSerializer(serializers.ModelSerializer):
    worker_phone = serializers.CharField(source="assignment.worker.phone", read_only=True)
    worker_name = serializers.SerializerMethodField()
    job_title = serializers.CharField(source="assignment.job.title", read_only=True)
    business_name = serializers.CharField(source="assignment.job.business.legal_name", read_only=True)
    business_phone = serializers.CharField(source="assignment.job.business.user.phone", read_only=True)
    amount_display = serializers.SerializerMethodField()
    declarations = serializers.SerializerMethodField()

    class Meta:
        model = WageObligation
        fields = [
            "id", "assignment", "worker_phone", "worker_name", "job_title", "business_name", "business_phone",
            "amount", "currency", "amount_display", "due_date", "status", "created_at",
            "declarations",
        ]
        read_only_fields = fields

    def get_worker_name(self, obj):
        try:
            return obj.assignment.worker.worker_profile.full_name
        except Exception:
            return None

    def get_amount_display(self, obj):
        return format_money(obj.amount)

    def get_declarations(self, obj):
        from wages.serializers import PaymentDeclarationSerializer
        return PaymentDeclarationSerializer(obj.declarations.all(), many=True).data


class PaymentDeclarationSerializer(serializers.ModelSerializer):
    declared_by_phone = serializers.CharField(source="declared_by.phone", read_only=True)

    class Meta:
        model = PaymentDeclaration
        fields = [
            "id", "wage_obligation", "declared_amount", "currency",
            "payment_date", "payment_method", "transaction_reference",
            "declared_by_phone", "declared_at", "status", "review_notes", "provider_confirmed",
        ]
        read_only_fields = ["id", "declared_by_phone", "declared_at", "status", "review_notes", "provider_confirmed"]


class PaymentDeclarationCreateSerializer(serializers.ModelSerializer):
    """Manual mode «حوّلت الأجر». The amount, currency and method are set by the server
    (agreed amount, ILS, Jawwal Pay); anything the client sends for them is ignored."""
    payment_date = serializers.DateField(required=False)
    # The Jawwal Pay transaction number is required: it is what the admin checks in a dispute.
    transaction_reference = serializers.CharField(
        max_length=PaymentDeclaration._meta.get_field("transaction_reference").max_length,
        trim_whitespace=True,
        error_messages={
            "required": "أدخل رقم العملية في Jawwal Pay.",
            "blank": "أدخل رقم العملية في Jawwal Pay.",
            "null": "أدخل رقم العملية في Jawwal Pay.",
        },
    )

    class Meta:
        model = PaymentDeclaration
        fields = ["payment_date", "transaction_reference"]


class PaymentEvidenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentEvidence
        fields = ["id", "original_filename", "content_type", "file_size", "uploaded_at"]
        read_only_fields = fields
