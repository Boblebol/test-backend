import pytest
from sqlalchemy.orm import Session

from app.modules.organizations.repository import OrganizationRepository


pytestmark = pytest.mark.integration


def test_organization_repository_lists_organizations_by_name(
    db_session: Session,
    persisted_org_user: object,
) -> None:
    states = OrganizationRepository(db_session).list()

    assert [state.name for state in states] == sorted(state.name for state in states)
    assert len(states) == 1
