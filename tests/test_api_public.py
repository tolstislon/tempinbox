import uuid
from datetime import UTC, datetime

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import Message


async def _insert_msg(
    db: AsyncSession,
    recipient: str = "user@tempinbox.dev",
    sender: str = "sender@example.com",
    subject: str = "Test Subject",
    body_text: str = "Hello body",
    body_html: str = "<p>Hello body</p>",
    domain: str | None = None,
) -> uuid.UUID:
    msg_id = uuid.uuid4()
    resolved_domain = domain or recipient.split("@")[1]
    msg = Message(
        id=msg_id,
        sender=sender,
        recipient=recipient,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        raw_headers={"From": [sender]},
        size_bytes=200,
        domain=resolved_domain,
        received_at=datetime.now(UTC),
    )
    db.add(msg)
    await db.commit()
    return msg_id


class TestHealth:
    async def test_health(self, client: httpx.AsyncClient):
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("healthy", "unhealthy")


class TestPublicAPI:
    async def test_unauthorized(self, client: httpx.AsyncClient):
        resp = await client.get("/api/v1/inbox/test@tempinbox.dev")
        assert resp.status_code == 422  # Missing header

    async def test_invalid_key(self, client: httpx.AsyncClient):
        resp = await client.get(
            "/api/v1/inbox/test@tempinbox.dev",
            headers={"X-API-Key": "invalid-key"},
        )
        assert resp.status_code == 401

    async def test_list_inbox(
        self,
        client: httpx.AsyncClient,
        test_api_key,
        db_session: AsyncSession,
    ):
        raw_key, _ = test_api_key
        await _insert_msg(db_session)

        resp = await client.get(
            "/api/v1/inbox/user@tempinbox.dev",
            headers={"X-API-Key": raw_key},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert len(data["messages"]) >= 1

    async def test_get_message(
        self,
        client: httpx.AsyncClient,
        test_api_key,
        db_session: AsyncSession,
    ):
        raw_key, _ = test_api_key
        msg_id = await _insert_msg(db_session)

        resp = await client.get(
            f"/api/v1/message/{msg_id}",
            headers={"X-API-Key": raw_key},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["body_text"] == "Hello body"
        assert data["body_html"] == "<p>Hello body</p>"

    async def test_get_message_not_found(
        self,
        client: httpx.AsyncClient,
        test_api_key,
    ):
        raw_key, _ = test_api_key
        resp = await client.get(
            f"/api/v1/message/{uuid.uuid4()}",
            headers={"X-API-Key": raw_key},
        )
        assert resp.status_code == 404

    async def test_inbox_stats(
        self,
        client: httpx.AsyncClient,
        test_api_key,
        db_session: AsyncSession,
    ):
        raw_key, _ = test_api_key
        await _insert_msg(db_session)

        resp = await client.get(
            "/api/v1/inbox/user@tempinbox.dev/stats",
            headers={"X-API-Key": raw_key},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_messages"] >= 1

    async def test_search_inbox(
        self,
        client: httpx.AsyncClient,
        test_api_key,
        db_session: AsyncSession,
    ):
        raw_key, _ = test_api_key
        await _insert_msg(db_session)

        resp = await client.get(
            "/api/v1/inbox/user@tempinbox.dev/search",
            params={"q": "Hello"},
            headers={"X-API-Key": raw_key},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1

    async def test_key_info(
        self,
        client: httpx.AsyncClient,
        test_api_key,
    ):
        raw_key, _ = test_api_key
        resp = await client.get(
            "/api/v1/key-info",
            headers={"X-API-Key": raw_key},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "test-key"

    async def test_domain_isolation_restricted_key(
        self,
        client: httpx.AsyncClient,
        restricted_api_key,
        db_session: AsyncSession,
    ):
        raw_key, _ = restricted_api_key
        await _insert_msg(db_session)

        resp = await client.get(
            "/api/v1/inbox/user@tempinbox.dev",
            headers={"X-API-Key": raw_key},
        )
        assert resp.status_code == 403

    async def test_domain_isolation_allowed(
        self,
        client: httpx.AsyncClient,
        restricted_api_key,
        db_session: AsyncSession,
    ):
        raw_key, _ = restricted_api_key
        await _insert_msg(db_session, recipient="user@restricted.dev")

        resp = await client.get(
            "/api/v1/inbox/user@restricted.dev",
            headers={"X-API-Key": raw_key},
        )
        assert resp.status_code == 200

    async def test_domain_isolation_unrestricted_key(
        self,
        client: httpx.AsyncClient,
        test_api_key,
        db_session: AsyncSession,
    ):
        raw_key, _ = test_api_key
        await _insert_msg(db_session, recipient="user@restricted.dev")
        await _insert_msg(db_session, recipient="user@tempinbox.dev")

        resp1 = await client.get(
            "/api/v1/inbox/user@restricted.dev",
            headers={"X-API-Key": raw_key},
        )
        assert resp1.status_code == 200

        resp2 = await client.get(
            "/api/v1/inbox/user@tempinbox.dev",
            headers={"X-API-Key": raw_key},
        )
        assert resp2.status_code == 200

    async def test_message_domain_isolation(
        self,
        client: httpx.AsyncClient,
        restricted_api_key,
        db_session: AsyncSession,
    ):
        raw_key, _ = restricted_api_key
        msg_id = await _insert_msg(db_session, recipient="user@tempinbox.dev")

        resp = await client.get(
            f"/api/v1/message/{msg_id}",
            headers={"X-API-Key": raw_key},
        )
        assert resp.status_code == 403

    async def test_deactivated_key_rejected(
        self,
        client: httpx.AsyncClient,
        inactive_api_key,
    ):
        raw_key, _ = inactive_api_key
        resp = await client.get(
            "/api/v1/inbox/user@tempinbox.dev",
            headers={"X-API-Key": raw_key},
        )
        assert resp.status_code == 401

    async def test_expired_key_rejected(
        self,
        client: httpx.AsyncClient,
        expired_api_key,
    ):
        raw_key, _ = expired_api_key
        resp = await client.get(
            "/api/v1/inbox/user@tempinbox.dev",
            headers={"X-API-Key": raw_key},
        )
        assert resp.status_code == 401

    async def test_list_inbox_pagination(
        self,
        client: httpx.AsyncClient,
        test_api_key,
        db_session: AsyncSession,
    ):
        raw_key, _ = test_api_key
        for i in range(3):
            await _insert_msg(
                db_session,
                recipient="paginated@tempinbox.dev",
                subject=f"Msg {i}",
            )

        resp = await client.get(
            "/api/v1/inbox/paginated@tempinbox.dev",
            params={"limit": 2, "offset": 0},
            headers={"X-API-Key": raw_key},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert len(data["messages"]) == 2

    async def test_list_inbox_filter_sender(
        self,
        client: httpx.AsyncClient,
        test_api_key,
        db_session: AsyncSession,
    ):
        raw_key, _ = test_api_key
        await _insert_msg(
            db_session,
            recipient="filtered@tempinbox.dev",
            sender="alice@example.com",
        )
        await _insert_msg(
            db_session,
            recipient="filtered@tempinbox.dev",
            sender="bob@example.com",
        )

        resp = await client.get(
            "/api/v1/inbox/filtered@tempinbox.dev",
            params={"sender": "alice@example.com"},
            headers={"X-API-Key": raw_key},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["messages"][0]["sender"] == "alice@example.com"

    async def test_list_inbox_filter_subject(
        self,
        client: httpx.AsyncClient,
        test_api_key,
        db_session: AsyncSession,
    ):
        raw_key, _ = test_api_key
        await _insert_msg(
            db_session,
            recipient="subfilter@tempinbox.dev",
            subject="Important Notice",
        )
        await _insert_msg(
            db_session,
            recipient="subfilter@tempinbox.dev",
            subject="Weekly Newsletter",
        )

        resp = await client.get(
            "/api/v1/inbox/subfilter@tempinbox.dev",
            params={"subject_contains": "Important"},
            headers={"X-API-Key": raw_key},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert "Important" in data["messages"][0]["subject"]

    async def test_search_inbox_subject_only(
        self,
        client: httpx.AsyncClient,
        test_api_key,
        db_session: AsyncSession,
    ):
        raw_key, _ = test_api_key
        await _insert_msg(
            db_session,
            recipient="searchsub@tempinbox.dev",
            subject="UniqueSubjectTerm",
            body_text="nothing here",
        )

        resp = await client.get(
            "/api/v1/inbox/searchsub@tempinbox.dev/search",
            params={"q": "UniqueSubjectTerm", "search_in": "subject"},
            headers={"X-API-Key": raw_key},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1

    async def test_search_inbox_empty_results(
        self,
        client: httpx.AsyncClient,
        test_api_key,
        db_session: AsyncSession,
    ):
        raw_key, _ = test_api_key
        await _insert_msg(db_session, recipient="emptysearch@tempinbox.dev")

        resp = await client.get(
            "/api/v1/inbox/emptysearch@tempinbox.dev/search",
            params={"q": "nonexistentxyz987"},
            headers={"X-API-Key": raw_key},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert len(data["messages"]) == 0

    async def test_get_message_invalid_uuid(
        self,
        client: httpx.AsyncClient,
        test_api_key,
    ):
        raw_key, _ = test_api_key
        resp = await client.get(
            "/api/v1/message/not-a-uuid",
            headers={"X-API-Key": raw_key},
        )
        assert resp.status_code == 422

    async def test_inbox_stats_empty(
        self,
        client: httpx.AsyncClient,
        test_api_key,
    ):
        raw_key, _ = test_api_key
        resp = await client.get(
            "/api/v1/inbox/nobody@tempinbox.dev/stats",
            headers={"X-API-Key": raw_key},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_messages"] == 0

    async def test_rate_limit_info(
        self,
        client: httpx.AsyncClient,
        test_api_key,
    ):
        raw_key, _ = test_api_key
        resp = await client.get(
            "/api/v1/rate-limit",
            headers={"X-API-Key": raw_key},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "limit_per_minute" in data
