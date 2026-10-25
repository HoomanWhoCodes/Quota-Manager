from rest_framework import serializers

from quotas.models import QUOTA_CEILING_MINUTES, Decision, DecisionOutcome, QuotaRequest, RequestStatus


class QuotaRequestCreateSerializer(serializers.Serializer):
    period_id = serializers.IntegerField(min_value=1)
    minutes = serializers.IntegerField(min_value=1, max_value=QUOTA_CEILING_MINUTES)
    reason = serializers.CharField(max_length=1000)


class QuotaRequestFilterSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=RequestStatus.choices, required=False)
    period_id = serializers.IntegerField(min_value=1, required=False)


class DecisionCreateSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=DecisionOutcome.choices)


class DecisionSerializer(serializers.ModelSerializer):
    actor_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = Decision
        fields = ["role", "outcome", "actor_id", "created_at"]


class QuotaRequestSerializer(serializers.ModelSerializer):
    employee_id = serializers.IntegerField(read_only=True)
    period_id = serializers.IntegerField(read_only=True)
    decisions = DecisionSerializer(many=True, read_only=True)

    class Meta:
        model = QuotaRequest
        fields = [
            "id",
            "employee_id",
            "period_id",
            "minutes",
            "reason",
            "status",
            "decisions",
            "created_at",
            "decided_at",
        ]


class DecisionResultSerializer(serializers.Serializer):
    def to_representation(self, decision):
        return {
            "decision": DecisionSerializer(decision).data,
            "request": {"id": decision.request_id, "status": decision.request.status},
        }


class QuotaSummarySerializer(serializers.Serializer):
    period_id = serializers.IntegerField()
    ceiling_minutes = serializers.IntegerField()
    consumed_minutes = serializers.IntegerField()
    remaining_minutes = serializers.IntegerField()
