from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Team, User


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ["name"]
    search_fields = ["name"]


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ["username", "role", "team", "is_staff"]
    list_filter = ["role", "team", "is_staff"]
    fieldsets = BaseUserAdmin.fieldsets + (("Organization", {"fields": ("role", "team")}),)
    add_fieldsets = BaseUserAdmin.add_fieldsets + (("Organization", {"fields": ("role", "team")}),)
