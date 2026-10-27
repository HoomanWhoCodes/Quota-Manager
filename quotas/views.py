from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from quotas import services
from quotas.permissions import CanSubmitRequest
from quotas.serializers import (
    DecisionCreateSerializer,
    DecisionResultSerializer,
    QuotaRequestCreateSerializer,
    QuotaRequestFilterSerializer,
    QuotaRequestSerializer,
    QuotaSummarySerializer,
)
from utils.idempotency import idempotent


class QuotaRequestListCreateView(generics.ListCreateAPIView):
    serializer_class = QuotaRequestSerializer
    permission_classes = [IsAuthenticated, CanSubmitRequest]

    def get_queryset(self):
        filters = QuotaRequestFilterSerializer(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        return services.list_requests(user=self.request.user, **filters.validated_data)

    @idempotent
    def create(self, request, *args, **kwargs):
        serializer = QuotaRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        quota_request = services.submit_request(employee=request.user, **serializer.validated_data)
        return Response(QuotaRequestSerializer(quota_request).data, status=status.HTTP_201_CREATED)


class QuotaRequestDetailView(generics.RetrieveAPIView):
    serializer_class = QuotaRequestSerializer

    def get_queryset(self):
        return services.list_requests(user=self.request.user)


class DecisionCreateView(APIView):
    @idempotent
    def post(self, request, pk):
        serializer = DecisionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        decision = services.decide(
            actor=request.user,
            request_id=pk,
            outcome=serializer.validated_data["decision"],
        )
        return Response(DecisionResultSerializer(decision).data, status=status.HTTP_200_OK)


class QuotaSummaryView(APIView):
    def get(self, request, period_id):
        summary = services.get_quota_summary(user=request.user, period_id=period_id)
        return Response(QuotaSummarySerializer(summary).data)
