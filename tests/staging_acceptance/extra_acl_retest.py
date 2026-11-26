"""Metadata-only policy assertions on the owned disposable database. ACL fixtures roll back."""

import pytest

from edu_api.db.staging import SECURITY_SQL


@pytest.mark.parametrize("privilege", ["MAINTAIN", "SELECT WITH GRANT OPTION"])
async def test_web_login_refuses_operational_or_delegable_catalog_rights(admin, privilege):
    async with admin.acquire() as db:
        tx = db.transaction()
        await tx.start()
        try:
            assert all((await db.fetchrow(SECURITY_SQL)).values())
            if privilege == "MAINTAIN":
                await db.execute("GRANT MAINTAIN ON app.courses TO edu_api_login")
            else:
                await db.execute("GRANT SELECT ON app.courses TO edu_api_login WITH GRANT OPTION")
            assert await db.fetchval(
                "SELECT has_table_privilege('edu_api_login', 'app.courses', $1)", privilege
            )
            assert not all((await db.fetchrow(SECURITY_SQL)).values()), (
                f"staging policy accepted surplus web-login privilege: {privilege}"
            )
        finally:
            await tx.rollback()
