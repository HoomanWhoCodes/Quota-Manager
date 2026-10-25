from rest_framework.permissions import BasePermission


class CanSubmitRequest(BasePermission):
    message = "Only employees can submit requests."

    def has_permission(self, request, view):
        if request.method != "POST":
            return True
        return request.user.is_employee
