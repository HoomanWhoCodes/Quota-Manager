from datetime import timedelta

import pytest
from rest_framework_simplejwt.tokens import AccessToken

from utils.testing.fixtures import PASSWORD

LOGIN_URL = "/api/v1/auth/token/"
REFRESH_URL = "/api/v1/auth/token/refresh/"
PROTECTED_URL = "/api/v1/requests/"


def login(client, username, password=PASSWORD):
    return client.post(LOGIN_URL, {"username": username, "password": password}, format="json")


@pytest.mark.django_db
class TestNotAuthenticated:
    def test_no_credentials_returns_401(self, api_client):
        response = api_client.get(PROTECTED_URL)

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "not_authenticated"
        assert response.headers["WWW-Authenticate"] == 'Bearer realm="api"'

    def test_unknown_auth_scheme_returns_401(self, api_client):
        api_client.credentials(HTTP_AUTHORIZATION="Basic abc")
        response = api_client.get(PROTECTED_URL)

        assert response.status_code == 401


@pytest.mark.django_db
class TestJWTLogin:
    def test_login_returns_access_and_refresh(self, api_client, employee):
        response = login(api_client, "alice")

        assert response.status_code == 200
        assert set(response.json()) == {"access", "refresh"}

    def test_wrong_password_returns_401(self, api_client, employee):
        response = login(api_client, "alice", password="wrong")

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "not_authenticated"

    def test_unknown_user_returns_401(self, api_client):
        response = login(api_client, "nobody")

        assert response.status_code == 401

    def test_inactive_user_cannot_log_in(self, api_client, employee):
        employee.is_active = False
        employee.save()

        response = login(api_client, "alice")

        assert response.status_code == 401

    def test_missing_fields_return_400(self, api_client):
        response = api_client.post(LOGIN_URL, {}, format="json")

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "validation_error"
        assert set(response.json()["error"]["details"]) == {"username", "password"}


@pytest.mark.django_db
class TestJWTAccess:
    def test_access_token_works_on_the_api(self, api_client, employee):
        access = login(api_client, "alice").json()["access"]
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        assert api_client.get(PROTECTED_URL).status_code == 200

    def test_invalid_token_returns_401_without_token_internals(self, api_client):
        api_client.credentials(HTTP_AUTHORIZATION="Bearer not.a.jwt")
        response = api_client.get(PROTECTED_URL)

        assert response.status_code == 401
        assert response.json() == {
            "error": {
                "code": "not_authenticated",
                "message": "Given token not valid for any token type",
                "details": None,
            }
        }

    def test_expired_token_returns_401(self, api_client, employee):
        token = AccessToken.for_user(employee)
        token.set_exp(lifetime=timedelta(seconds=-1))
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        assert api_client.get(PROTECTED_URL).status_code == 401

    def test_token_of_deleted_user_returns_401(self, api_client, make_user, team):
        user = make_user("temp", team=team)
        token = AccessToken.for_user(user)
        user.delete()
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        assert api_client.get(PROTECTED_URL).status_code == 401


@pytest.mark.django_db
class TestJWTRefresh:
    def test_refresh_returns_new_access_token(self, api_client, employee):
        refresh = login(api_client, "alice").json()["refresh"]
        response = api_client.post(REFRESH_URL, {"refresh": refresh}, format="json")

        assert response.status_code == 200
        assert "access" in response.json()

    def test_access_token_cannot_be_used_as_refresh(self, api_client, employee):
        access = login(api_client, "alice").json()["access"]
        response = api_client.post(REFRESH_URL, {"refresh": access}, format="json")

        assert response.status_code == 401


@pytest.mark.django_db
class TestTokenAuth:
    def test_token_works_on_the_api(self, client_for, employee):
        assert client_for(employee).get(PROTECTED_URL).status_code == 200

    def test_wrong_token_returns_401(self, api_client):
        api_client.credentials(HTTP_AUTHORIZATION="Token does-not-exist")

        assert api_client.get(PROTECTED_URL).status_code == 401
