import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import Message


class TestAdminAPI:
    async def test_unauthorized(self, client: httpx.AsyncClient):
        resp = await client.get("/admin/keys")
        assert resp.status_code == 422

    async def test_invalid_master_key(self, client: httpx.AsyncClient):
        resp = await client.get(
            "/admin/keys",
            headers={"X-Master-Key": "wrong-key"},
        )
        assert resp.status_code == 401

    async def test_create_and_list_keys(self, client: httpx.AsyncClient, master_key):
        # Create
        resp = await client.post(
            "/admin/keys",
            json={"name": "test-admin-key"},
            headers={"X-Master-Key": master_key},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "key" in data
        assert data["key"].startswith("tempinbox_")
        key_id = data["id"]

        # List
        resp = await client.get(
            "/admin/keys",
            headers={"X-Master-Key": master_key},
        )
        assert resp.status_code == 200
        keys = resp.json()
        assert any(k["id"] == key_id for k in keys)

        # Get
        resp = await client.get(
            f"/admin/keys/{key_id}",
            headers={"X-Master-Key": master_key},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "test-admin-key"

        # Update
        resp = await client.patch(
            f"/admin/keys/{key_id}",
            json={"name": "updated-name"},
            headers={"X-Master-Key": master_key},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "updated-name"

        # Deactivate
        resp = await client.delete(
            f"/admin/keys/{key_id}",
            headers={"X-Master-Key": master_key},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "deactivated"

    async def test_blacklist_crud(self, client: httpx.AsyncClient, master_key):
        # Create
        resp = await client.post(
            "/admin/blacklist",
            json={"pattern": "spam@evil.com", "block_type": "hard", "reason": "spam"},
            headers={"X-Master-Key": master_key},
        )
        assert resp.status_code == 200
        entry_id = resp.json()["id"]

        # List
        resp = await client.get(
            "/admin/blacklist",
            headers={"X-Master-Key": master_key},
        )
        assert resp.status_code == 200
        assert any(e["id"] == entry_id for e in resp.json())

        # Update
        resp = await client.patch(
            f"/admin/blacklist/{entry_id}",
            json={"block_type": "soft"},
            headers={"X-Master-Key": master_key},
        )
        assert resp.status_code == 200
        assert resp.json()["block_type"] == "soft"

        # Delete
        resp = await client.delete(
            f"/admin/blacklist/{entry_id}",
            headers={"X-Master-Key": master_key},
        )
        assert resp.status_code == 200

    async def test_blacklist_import(self, client: httpx.AsyncClient, master_key):
        resp = await client.post(
            "/admin/blacklist/import",
            json={
                "patterns": [
                    {"pattern": "import1@evil.com"},
                    {"pattern": "import2@evil.com"},
                ],
            },
            headers={"X-Master-Key": master_key},
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    async def test_admin_stats(self, client: httpx.AsyncClient, master_key):
        resp = await client.get(
            "/admin/stats",
            headers={"X-Master-Key": master_key},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "total_messages" in data
        assert "total_api_keys" in data

    async def test_delete_old_messages(
        self, client: httpx.AsyncClient, master_key, db_session: AsyncSession
    ):
        now = datetime.now(UTC)
        old_msg = Message(
            sender="old@example.com",
            recipient="box@test.dev",
            subject="Old",
            size_bytes=100,
            received_at=now - timedelta(days=10),
            domain="test.dev",
        )
        new_msg = Message(
            sender="new@example.com",
            recipient="box@test.dev",
            subject="New",
            size_bytes=100,
            received_at=now - timedelta(hours=1),
            domain="test.dev",
        )
        db_session.add_all([old_msg, new_msg])
        await db_session.commit()

        resp = await client.delete(
            "/admin/messages/old?days=1",
            headers={"X-Master-Key": master_key},
        )
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 1

    async def test_delete_old_messages_none_old(self, client: httpx.AsyncClient, master_key):
        resp = await client.delete(
            "/admin/messages/old?days=1",
            headers={"X-Master-Key": master_key},
        )
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 0

    async def test_clear_inbox(
        self, client: httpx.AsyncClient, master_key, db_session: AsyncSession
    ):
        email = "clearme@test.dev"
        for i in range(2):
            db_session.add(
                Message(
                    sender=f"sender{i}@example.com",
                    recipient=email,
                    subject=f"msg {i}",
                    size_bytes=50,
                    domain="test.dev",
                )
            )
        await db_session.commit()

        resp = await client.delete(
            f"/admin/inbox/{email}",
            headers={"X-Master-Key": master_key},
        )
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 2

    async def test_clear_inbox_empty(self, client: httpx.AsyncClient, master_key):
        resp = await client.delete(
            "/admin/inbox/nobody@test.dev",
            headers={"X-Master-Key": master_key},
        )
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 0

    async def test_get_key_not_found(self, client: httpx.AsyncClient, master_key):
        fake_id = uuid.uuid4()
        resp = await client.get(
            f"/admin/keys/{fake_id}",
            headers={"X-Master-Key": master_key},
        )
        assert resp.status_code == 404

    async def test_delete_key_not_found(self, client: httpx.AsyncClient, master_key):
        fake_id = uuid.uuid4()
        resp = await client.delete(
            f"/admin/keys/{fake_id}",
            headers={"X-Master-Key": master_key},
        )
        assert resp.status_code == 404

    async def test_create_key_with_domains_and_expiry(self, client: httpx.AsyncClient, master_key):
        expires = (datetime.now(UTC) + timedelta(days=30)).isoformat()
        resp = await client.post(
            "/admin/keys",
            json={
                "name": "domain-key",
                "domains": ["example.com", "test.dev"],
                "expires_at": expires,
            },
            headers={"X-Master-Key": master_key},
        )
        assert resp.status_code == 200
        key_id = resp.json()["id"]

        resp = await client.get(
            f"/admin/keys/{key_id}",
            headers={"X-Master-Key": master_key},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["domains"] == ["example.com", "test.dev"]
        assert data["expires_at"] is not None

    async def test_brute_force_lockout(self, app, client: httpx.AsyncClient):
        # Clear any existing brute force state
        await app.state.redis.flushdb()

        for _ in range(6):
            await client.get(
                "/admin/keys",
                headers={"X-Master-Key": "wrong-key"},
            )
        resp = await client.get(
            "/admin/keys",
            headers={"X-Master-Key": "wrong-key"},
        )
        assert resp.status_code == 429

        # Clean up brute force counter so subsequent tests aren't affected
        await app.state.redis.flushdb()
