import json

import pytest
from django.test import RequestFactory

from utils.errors import server_error_view

NOT_FOUND = {"error": {"code": "not_found", "message": "Not found.", "details": None}}


@pytest.mark.django_db
class TestErrorsOutsideViews:
    def test_unknown_url_returns_json_404(self, client_for, employee):
        response = client_for(employee).get("/api/v1/does-not-exist/")

        assert response.status_code == 404
        assert response.json() == NOT_FOUND

    def test_id_that_is_not_a_number_returns_json_404(self, client_for, employee):
        response = client_for(employee).get("/api/v1/requests/abc/")

        assert response.status_code == 404
        assert response.json() == NOT_FOUND

    def test_missing_trailing_slash_is_404_not_a_redirect(self, client_for, employee):
        client = client_for(employee)

        assert client.get("/api/v1/requests").status_code == 404
        assert client.post("/api/v1/requests", {}, format="json").status_code == 404


def test_server_error_returns_json_500():
    response = server_error_view(RequestFactory().get("/"))

    assert response.status_code == 500
    assert json.loads(response.content) == {
        "error": {"code": "server_error", "message": "Something went wrong.", "details": None}
    }
