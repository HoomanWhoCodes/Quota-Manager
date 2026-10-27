from quotas.models import QuotaRequest

# Used by the list, the detail and decisions, so the rule lives in one place.
def visible_requests(user):
    qs = QuotaRequest.objects.all()
    if user.is_hr:
        return qs
    if user.is_manager:
        return qs.filter(employee__team_id=user.team_id)
    return qs.filter(employee=user)
