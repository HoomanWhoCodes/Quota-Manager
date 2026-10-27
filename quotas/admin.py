from django.contrib import admin

from utils.admin import ReadOnlyAdmin

from .models import Decision, Period, Quota, QuotaRequest, RequestEvent


@admin.register(Period)
class PeriodAdmin(admin.ModelAdmin):
    list_display = ["name", "start_at", "end_at"]
    search_fields = ["name"]


# Everything below changes only through the API (with locks, quota checks and
# audit events), so the admin only shows it.


class DecisionInline(admin.TabularInline):
    model = Decision
    fields = ["role", "outcome", "actor", "created_at"]
    readonly_fields = fields
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class RequestEventInline(admin.TabularInline):
    model = RequestEvent
    fields = ["event_type", "actor", "created_at"]
    readonly_fields = fields
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(QuotaRequest)
class QuotaRequestAdmin(ReadOnlyAdmin):
    list_display = ["id", "employee", "period", "minutes", "status", "created_at", "decided_at"]
    list_filter = ["status", "period"]
    search_fields = ["employee__username"]
    inlines = [DecisionInline, RequestEventInline]


@admin.register(Quota)
class QuotaAdmin(ReadOnlyAdmin):
    list_display = ["employee", "period", "consumed_minutes", "remaining_minutes", "updated_at"]
    list_filter = ["period"]
    search_fields = ["employee__username"]


@admin.register(Decision)
class DecisionAdmin(ReadOnlyAdmin):
    list_display = ["request", "role", "outcome", "actor", "created_at"]
    list_filter = ["role", "outcome"]
    search_fields = ["actor__username"]


@admin.register(RequestEvent)
class RequestEventAdmin(ReadOnlyAdmin):
    list_display = ["request", "event_type", "actor", "created_at"]
    list_filter = ["event_type"]
    search_fields = ["actor__username"]
