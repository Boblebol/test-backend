from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import OrganizationORM, UserORM
from app.db.session import SessionLocal
from app.modules.auth.passwords import hash_password


DEMO_PASSWORD = "primmo-demo"
DEMO_ACCOUNTS = (
    ("Primmo Alpha", "alpha@example.com"),
    ("Primmo Beta", "beta@example.com"),
)


@dataclass(frozen=True)
class SeedResult:
    created_organizations: int
    created_users: int


def seed_demo_data(session: Session) -> SeedResult:
    created_organizations = 0
    created_users = 0

    for organization_name, email in DEMO_ACCOUNTS:
        organization = session.scalar(
            select(OrganizationORM).where(OrganizationORM.name == organization_name)
        )
        if organization is None:
            organization = OrganizationORM(name=organization_name)
            session.add(organization)
            session.flush()
            created_organizations += 1

        user = session.scalar(select(UserORM).where(UserORM.email == email))
        if user is None:
            session.add(
                UserORM(
                    org_id=organization.id,
                    email=email,
                    password_hash=hash_password(DEMO_PASSWORD),
                )
            )
            created_users += 1

    session.flush()
    return SeedResult(
        created_organizations=created_organizations,
        created_users=created_users,
    )


def main() -> None:
    with SessionLocal() as session:
        result = seed_demo_data(session)
        session.commit()

    print(
        "Seed complete: "
        f"{result.created_organizations} organizations created, "
        f"{result.created_users} users created."
    )
    print(f"Demo password: {DEMO_PASSWORD}")


if __name__ == "__main__":
    main()
