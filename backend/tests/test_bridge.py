"""Step 6: the auth bridge, against the real database.

Needs Postgres running and seeded (docker compose up; python -m scripts.seed).
Each test runs inside a transaction that is rolled back.
"""

import asyncio
import uuid

import asyncpg
import pytest

from app.auth.bridge import AuthBridgeError, principal_from_okta, role_from_groups
from app.config import settings

ISSUER = "https://test-okta.example/oauth2/default"


@pytest.mark.parametrize(
    "groups, role",
    [
        (["gk-employee"], "employee"),
        (["gk-hr-manager"], "hr_manager"),
        (["gk-admin"], "admin"),
        (["gk-admin", "gk-employee"], "employee"),  # lowest role wins
        (["gk-hr-manager", "Everyone", "gk-admin"], "hr_manager"),
    ],
)
def test_role_from_groups(groups, role):
    assert role_from_groups(groups) == role


@pytest.mark.parametrize("groups", [[], ["Everyone"], ["gk-superuser"], ["GK-ADMIN"]])
def test_no_gatekeeper_group_is_refused(groups):
    with pytest.raises(AuthBridgeError):
        role_from_groups(groups)


def run_in_rollback(test):
    """Give the test a connection with a fresh test tenant; undo everything after."""
    async def main():
        conn = await asyncpg.connect(settings.database_url)
        tx = conn.transaction()
        await tx.start()
        try:
            tenant_id = await conn.fetchval(
                "INSERT INTO tenants (name, idp_type, idp_issuer) VALUES ($1, 'okta_oidc', $2) RETURNING id",
                f"Test Tenant {uuid.uuid4()}", ISSUER,
            )
            await test(conn, str(tenant_id))
        finally:
            await tx.rollback()
            await conn.close()
    asyncio.run(main())


def claims(**overrides) -> dict:
    return {"iss": ISSUER, "sub": "00uTEST", "email": "pat@test.example", "groups": ["gk-hr-manager"], **overrides}


def test_first_login_creates_user():
    async def test(conn, tenant_id):
        p = await principal_from_okta(conn, claims())
        assert (p.tenant_id, p.email, p.role, p.scopes) == (tenant_id, "pat@test.example", "hr_manager", ("docs:read",))
        row = await conn.fetchrow("SELECT tenant_id, external_id, role FROM users WHERE id = $1", uuid.UUID(p.user_id))
        assert (str(row["tenant_id"]), row["external_id"], row["role"]) == (tenant_id, "00uTEST", "hr_manager")
    run_in_rollback(test)


def test_second_login_reuses_user_and_refreshes_role():
    async def test(conn, tenant_id):
        first = await principal_from_okta(conn, claims())
        second = await principal_from_okta(conn, claims(groups=["gk-admin"], email="Pat.New@Test.example"))
        assert second.user_id == first.user_id
        assert (second.role, second.email, second.scopes) == ("admin", "pat.new@test.example", ("docs:read", "docs:admin"))
    run_in_rollback(test)


def test_first_login_adopts_precreated_user_by_email():
    async def test(conn, tenant_id):
        seeded = await conn.fetchval(
            "INSERT INTO users (tenant_id, email, role) VALUES ($1, 'pat@test.example', 'employee') RETURNING id",
            uuid.UUID(tenant_id),
        )
        p = await principal_from_okta(conn, claims())
        assert p.user_id == str(seeded)
        assert await conn.fetchval("SELECT external_id FROM users WHERE id = $1", seeded) == "00uTEST"
    run_in_rollback(test)


def test_cannot_take_over_email_linked_to_another_idp_user():
    async def test(conn, tenant_id):
        await principal_from_okta(conn, claims(sub="00uOWNER"))
        with pytest.raises(AuthBridgeError, match="different IdP user"):
            await principal_from_okta(conn, claims(sub="00uATTACKER"))
    run_in_rollback(test)


def test_deactivated_user_is_refused():
    async def test(conn, tenant_id):
        p = await principal_from_okta(conn, claims())
        await conn.execute("UPDATE users SET active = false WHERE id = $1", uuid.UUID(p.user_id))
        with pytest.raises(AuthBridgeError, match="deactivated"):
            await principal_from_okta(conn, claims())
    run_in_rollback(test)


def test_unknown_issuer_is_refused():
    async def test(conn, tenant_id):
        with pytest.raises(AuthBridgeError, match="no tenant"):
            await principal_from_okta(conn, claims(iss="https://someone-elses-okta.example"))
    run_in_rollback(test)


def test_tenant_comes_from_issuer_not_claims():
    async def test(conn, tenant_id):
        globex = await conn.fetchval("SELECT id FROM tenants WHERE name = 'Globex'")
        # Extra claims a user might control can't move them to another tenant.
        p = await principal_from_okta(conn, claims(tenant_id=str(globex), tenant="Globex"))
        assert p.tenant_id == tenant_id
    run_in_rollback(test)


def test_missing_email_is_refused():
    async def test(conn, tenant_id):
        with pytest.raises(AuthBridgeError, match="no email"):
            await principal_from_okta(conn, claims(email=None))
    run_in_rollback(test)
