import pytest
from django.db import IntegrityError
from django.db.models import ProtectedError

from accounts.models import Team, User


@pytest.mark.django_db
class TestTeam:
    def test_name_is_unique(self, team):
        with pytest.raises(IntegrityError):
            Team.objects.create(name=team.name)

    def test_cannot_delete_team_with_members(self, team, employee):
        with pytest.raises(ProtectedError):
            team.delete()

    def test_str_is_name(self, team):
        assert str(team) == "Engineering"


@pytest.mark.django_db
class TestUserConstraints:
    def test_employee_needs_a_team(self):
        with pytest.raises(IntegrityError):
            User.objects.create(username="no-team", role=User.Role.EMPLOYEE)

    def test_manager_needs_a_team(self):
        with pytest.raises(IntegrityError):
            User.objects.create(username="no-team", role=User.Role.MANAGER)

    def test_hr_can_have_no_team(self):
        user = User.objects.create(username="hr", role=User.Role.HR)
        assert user.team is None

    def test_role_must_be_valid(self, team):
        with pytest.raises(IntegrityError):
            User.objects.create(username="boss", role="boss", team=team)

    def test_default_role_is_employee(self, team):
        user = User.objects.create(username="new", team=team)
        assert user.role == User.Role.EMPLOYEE

    def test_team_can_have_many_employees(self, make_user, team):
        make_user("e1", team=team)
        make_user("e2", team=team)
        assert team.members.count() == 2

    def test_team_can_have_more_than_one_manager(self, make_user, team):
        make_user("m1", role=User.Role.MANAGER, team=team)
        make_user("m2", role=User.Role.MANAGER, team=team)
        assert team.members.filter(role=User.Role.MANAGER).count() == 2


@pytest.mark.django_db
class TestUserRoleHelpers:
    def test_employee(self, employee):
        assert (employee.is_employee, employee.is_manager, employee.is_hr) == (True, False, False)

    def test_manager(self, manager):
        assert (manager.is_employee, manager.is_manager, manager.is_hr) == (False, True, False)

    def test_hr(self, hr):
        assert (hr.is_employee, hr.is_manager, hr.is_hr) == (False, False, True)
