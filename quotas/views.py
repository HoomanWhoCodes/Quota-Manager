from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from quotas import services
from quotas.permissions import CanSubmitRequest
from quotas.serializers import (
    DecisionCreateSerializer,
    DecisionSerializer,
    PeriodSerializer,
    QuotaRequestCreateSerializer,
    QuotaRequestFilterSerializer,
    QuotaRequestSerializer,
)
from quotas.models import Period
from utils.idempotency import idempotent


class PeriodListView(generics.ListAPIView):
    """Read-only list of periods, so clients can find the open one."""

    queryset = Period.objects.order_by("-start_at", "-id")
    serializer_class = PeriodSerializer
    pagination_class = None


class QuotaRequestListCreateView(generics.ListCreateAPIView):
    serializer_class = QuotaRequestSerializer
    permission_classes = [IsAuthenticated, CanSubmitRequest]  # only employees can submit

    def get_queryset(self):
        filters = QuotaRequestFilterSerializer(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        return services.list_requests(user=self.request.user, **filters.validated_data)

    @idempotent  # needs an Idempotency-Key header
    def create(self, request, *args, **kwargs):
        serializer = QuotaRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        quota_request = services.submit_request(employee=request.user, **serializer.validated_data)
        return Response(QuotaRequestSerializer(quota_request).data, status=201)


class QuotaRequestDetailView(generics.RetrieveAPIView):
    serializer_class = QuotaRequestSerializer

    def get_queryset(self):
        return services.list_requests(user=self.request.user)


class DecisionCreateView(APIView):  # who can decide is checked in the service layer
    @idempotent
    def post(self, request, pk):
        serializer = DecisionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        decision = services.decide(actor=request.user, request_id=pk, outcome=serializer.validated_data["decision"])
        return Response({
            "decision": DecisionSerializer(decision).data,
            "request": {"id": decision.request_id, "status": decision.request.status},
        })


class QuotaSummaryView(APIView):
    def get(self, request, period_id):
        return Response(services.get_quota_summary(user=request.user, period_id=period_id))
