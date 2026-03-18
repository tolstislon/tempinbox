#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-http://localhost:8000}"
SMTP_HOST="${2:-localhost}"
SMTP_PORT="${SMTP_PORT:-2525}"
MASTER_KEY="${MASTER_KEY:?Set MASTER_KEY env var}"
DOMAIN="${DOMAIN:-tempinbox.dev}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

PASSED=0
FAILED=0
TOTAL=0

pass() {
    PASSED=$((PASSED + 1))
    TOTAL=$((TOTAL + 1))
    echo -e "  ${GREEN}PASS${NC} $1"
}

fail() {
    FAILED=$((FAILED + 1))
    TOTAL=$((TOTAL + 1))
    echo -e "  ${RED}FAIL${NC} $1: $2"
}

echo "Smoke test against ${BASE_URL} (SMTP: ${SMTP_HOST}:${SMTP_PORT})"
echo ""

# ── S1: Health check ──────────────────────────────────────────────────
echo "S1: Health check"
HEALTH=$(curl -sf "$BASE_URL/health" 2>/dev/null || echo '{}')
HEALTH_STATUS=$(echo "$HEALTH" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || echo "")

if [ "$HEALTH_STATUS" = "healthy" ]; then
    pass "GET /health -> status=healthy"
else
    fail "GET /health" "expected status=healthy, got '$HEALTH_STATUS'"
fi

# ── S2: Create API key ───────────────────────────────────────────────
echo "S2: Create API key"
KEY_RESP=$(curl -sf -X POST "$BASE_URL/admin/keys" \
    -H "X-Master-Key: $MASTER_KEY" \
    -H "Content-Type: application/json" \
    -d '{"name": "smoke-test"}' 2>/dev/null || echo '{}')

API_KEY=$(echo "$KEY_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('key',''))" 2>/dev/null || echo "")
KEY_ID=$(echo "$KEY_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || echo "")

if [ -n "$API_KEY" ] && [ "$API_KEY" != "" ]; then
    pass "POST /admin/keys -> got key"
else
    fail "POST /admin/keys" "no key returned"
fi

# ── S3: Key info ─────────────────────────────────────────────────────
echo "S3: Key info"
KEY_INFO=$(curl -sf "$BASE_URL/api/v1/key-info" \
    -H "X-Api-Key: $API_KEY" 2>/dev/null || echo '{}')

KEY_INFO_ACTIVE=$(echo "$KEY_INFO" | python3 -c "import sys,json; print(json.load(sys.stdin).get('is_active',''))" 2>/dev/null || echo "")

if [ "$KEY_INFO_ACTIVE" = "True" ]; then
    pass "GET /api/v1/key-info -> is_active=True"
else
    fail "GET /api/v1/key-info" "expected is_active=True, got '$KEY_INFO_ACTIVE'"
fi

# ── S4: Empty inbox ──────────────────────────────────────────────────
echo "S4: Empty inbox"
TIMESTAMP=$(date +%s)
SMOKE_EMAIL="smoke-${TIMESTAMP}@${DOMAIN}"
INBOX_RESP=$(curl -sf "$BASE_URL/api/v1/inbox/$SMOKE_EMAIL" \
    -H "X-Api-Key: $API_KEY" 2>/dev/null || echo '{}')

INBOX_TOTAL=$(echo "$INBOX_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('total',''))" 2>/dev/null || echo "")

if [ "$INBOX_TOTAL" = "0" ]; then
    pass "GET /api/v1/inbox/$SMOKE_EMAIL -> total=0"
else
    fail "GET /api/v1/inbox/$SMOKE_EMAIL" "expected total=0, got '$INBOX_TOTAL'"
fi

# ── S5: SMTP connect ─────────────────────────────────────────────────
echo "S5: SMTP connect"
SMTP_OK=$(python3 -c "
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(5)
try:
    s.connect(('$SMTP_HOST', $SMTP_PORT))
    data = s.recv(1024)
    print('ok' if b'220' in data else 'fail')
except Exception as e:
    print(f'fail: {e}')
finally:
    s.close()
" 2>/dev/null || echo "fail")

if [ "$SMTP_OK" = "ok" ]; then
    pass "SMTP connect to ${SMTP_HOST}:${SMTP_PORT}"
else
    fail "SMTP connect" "$SMTP_OK"
fi

# ── S6: Send email via SMTP ──────────────────────────────────────────
echo "S6: Send email via SMTP"
SEND_EMAIL="smoke-send-${TIMESTAMP}@${DOMAIN}"
SMTP_SEND=$(python3 -c "
import smtplib
from email.mime.text import MIMEText

msg = MIMEText('Smoke test body')
msg['Subject'] = 'Smoke Test'
msg['From'] = 'smoker@example.com'
msg['To'] = '$SEND_EMAIL'

try:
    with smtplib.SMTP('$SMTP_HOST', $SMTP_PORT) as smtp:
        smtp.sendmail('smoker@example.com', '$SEND_EMAIL', msg.as_string())
    print('ok')
except Exception as e:
    print(f'fail: {e}')
" 2>/dev/null || echo "fail")

if [ "$SMTP_SEND" = "ok" ]; then
    pass "Send email to $SEND_EMAIL"
else
    fail "Send email via SMTP" "$SMTP_SEND"
fi

# Wait for message to be processed
sleep 1

# Get the message ID from inbox
MSG_ID=""
if [ "$SMTP_SEND" = "ok" ]; then
    INBOX2=$(curl -sf "$BASE_URL/api/v1/inbox/$SEND_EMAIL" \
        -H "X-Api-Key: $API_KEY" 2>/dev/null || echo '{}')
    MSG_ID=$(echo "$INBOX2" | python3 -c "import sys,json; msgs=json.load(sys.stdin).get('messages',[]); print(msgs[0]['id'] if msgs else '')" 2>/dev/null || echo "")
fi

# ── S7: Get message by ID ────────────────────────────────────────────
echo "S7: Get message by ID"
if [ -n "$MSG_ID" ]; then
    MSG_RESP=$(curl -sf "$BASE_URL/api/v1/message/$MSG_ID" \
        -H "X-Api-Key: $API_KEY" 2>/dev/null || echo '{}')

    MSG_SUBJECT=$(echo "$MSG_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('subject',''))" 2>/dev/null || echo "")

    if [ "$MSG_SUBJECT" = "Smoke Test" ]; then
        pass "GET /api/v1/message/$MSG_ID -> subject='Smoke Test'"
    else
        fail "GET /api/v1/message/$MSG_ID" "expected subject='Smoke Test', got '$MSG_SUBJECT'"
    fi
else
    fail "GET /api/v1/message/{id}" "no message ID available (send may have failed)"
fi

# ── S8: Admin stats ──────────────────────────────────────────────────
echo "S8: Admin stats"
STATS=$(curl -sf "$BASE_URL/admin/stats" \
    -H "X-Master-Key: $MASTER_KEY" 2>/dev/null || echo '{}')

STATS_KEYS=$(echo "$STATS" | python3 -c "
import sys,json
d = json.load(sys.stdin)
keys = sorted(d.keys())
print(','.join(keys))
" 2>/dev/null || echo "")

if echo "$STATS_KEYS" | grep -q "total_api_keys" && echo "$STATS_KEYS" | grep -q "total_messages"; then
    pass "GET /admin/stats -> has expected fields"
else
    fail "GET /admin/stats" "unexpected response keys: '$STATS_KEYS'"
fi

# ── S9: Deactivate key, then verify 401 ──────────────────────────────
echo "S9: Deactivate key and verify 401"
if [ -n "$KEY_ID" ]; then
    DEL_RESP=$(curl -sf -X DELETE "$BASE_URL/admin/keys/$KEY_ID" \
        -H "X-Master-Key: $MASTER_KEY" 2>/dev/null || echo '{}')

    DEL_STATUS=$(echo "$DEL_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || echo "")

    if [ "$DEL_STATUS" != "deactivated" ]; then
        fail "DELETE /admin/keys/$KEY_ID" "expected status=deactivated, got '$DEL_STATUS'"
    else
        # Verify that the deactivated key returns 401
        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/api/v1/key-info" \
            -H "X-Api-Key: $API_KEY" 2>/dev/null || echo "000")

        if [ "$HTTP_CODE" = "401" ]; then
            pass "Deactivated key returns 401"
        else
            fail "Deactivated key" "expected HTTP 401, got $HTTP_CODE"
        fi
    fi
else
    fail "Deactivate key" "no key ID available"
fi

# ── Summary ───────────────────────────────────────────────────────────
echo ""
echo "========================================="
if [ "$FAILED" -eq 0 ]; then
    echo -e "  ${GREEN}ALL $TOTAL CHECKS PASSED${NC}"
else
    echo -e "  ${GREEN}$PASSED passed${NC}, ${RED}$FAILED failed${NC} out of $TOTAL"
fi
echo "========================================="

exit "$FAILED"
