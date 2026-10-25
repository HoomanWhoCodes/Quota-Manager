from quotas.exceptions import NotFound
from quotas.models import QUOTA_CEILING_MINUTES, Period, Quota


def get_quota_summary(*, user, period_id):
    if not Period.objects.filter(pk=period_id).exists():
        raise NotFound()

    quota = Quota.objects.filter(employee=user, period_id=period_id).first()
    consumed = quota.consumed_minutes if quota else 0
    return {
        "period_id": period_id,
        "ceiling_minutes": QUOTA_CEILING_MINUTES,
        "consumed_minutes": consumed,
        "remaining_minutes": QUOTA_CEILING_MINUTES - consumed,
    }
