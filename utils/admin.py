from django.contrib import admin

from .models import IdempotencyKey


class ReadOnlyAdmin(admin.ModelAdmin):
    """For records that must only change through the API, never by hand."""

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(IdempotencyKey)
class IdempotencyKeyAdmin(ReadOnlyAdmin):
    list_display = ["key", "user", "response_status", "created_at"]
    list_filter = ["response_status"]
    search_fields = ["key", "user__username"]
