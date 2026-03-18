#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="docker-compose.test.yml"
MASTER_KEY="integration-test-key"
BASE_URL="http://localhost:8000"
SMTP_HOST="localhost"
SMTP_PORT="2525"

cleanup() {
    echo ""
    echo "=== Cleaning up ==="
    docker compose -f "$COMPOSE_FILE" down -v 2>/dev/null || true
}
trap cleanup EXIT

echo "=== Starting services ==="
docker compose -f "$COMPOSE_FILE" up -d --build --wait

echo "=== Waiting for API to be healthy ==="
MAX_RETRIES=30
for i in $(seq 1 $MAX_RETRIES); do
    STATUS=$(curl -sf "$BASE_URL/health" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])" 2>/dev/null || echo "unavailable")
    if [ "$STATUS" = "healthy" ]; then
        echo "API is healthy (attempt $i)"
        break
    fi
    if [ "$i" -eq "$MAX_RETRIES" ]; then
        echo "ERROR: API did not become healthy after $MAX_RETRIES attempts"
        docker compose -f "$COMPOSE_FILE" logs api
        exit 1
    fi
    echo "Waiting for API... (attempt $i/$MAX_RETRIES)"
    sleep 2
done

echo ""
echo "=== Step 1: Create API key ==="
KEY_RESPONSE=$(curl -sf -X POST "$BASE_URL/admin/keys" \
    -H "X-Master-Key: $MASTER_KEY" \
    -H "Content-Type: application/json" \
    -d '{"name": "integration-test"}')

echo "Key response: $KEY_RESPONSE"

API_KEY=$(echo "$KEY_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['key'])")
KEY_ID=$(echo "$KEY_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "API Key: $API_KEY"
echo "Key ID: $KEY_ID"

echo ""
echo "=== Step 2: Send email via SMTP ==="
RECIPIENT="test-$(date +%s)@tempinbox.dev"
echo "Sending to: $RECIPIENT"

python3 -c "
import smtplib
from email.mime.text import MIMEText

msg = MIMEText('Hello from integration test!')
msg['Subject'] = 'Integration Test Email'
msg['From'] = 'sender@example.com'
msg['To'] = '$RECIPIENT'

with smtplib.SMTP('$SMTP_HOST', $SMTP_PORT) as smtp:
    smtp.sendmail('sender@example.com', '$RECIPIENT', msg.as_string())
    print('Email sent successfully')
"

# Give the server a moment to process
sleep 1

echo ""
echo "=== Step 3: Check inbox ==="
INBOX_RESPONSE=$(curl -sf "$BASE_URL/api/v1/inbox/$RECIPIENT" \
    -H "X-Api-Key: $API_KEY")

echo "Inbox response: $INBOX_RESPONSE"

TOTAL=$(echo "$INBOX_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['total'])")
if [ "$TOTAL" -lt 1 ]; then
    echo "ERROR: Expected at least 1 message, got $TOTAL"
    exit 1
fi
echo "Found $TOTAL message(s) in inbox"

MESSAGE_ID=$(echo "$INBOX_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['messages'][0]['id'])")
echo "Message ID: $MESSAGE_ID"

echo ""
echo "=== Step 4: Get message by ID ==="
MSG_RESPONSE=$(curl -sf "$BASE_URL/api/v1/message/$MESSAGE_ID" \
    -H "X-Api-Key: $API_KEY")

echo "Message response: $MSG_RESPONSE"

SUBJECT=$(echo "$MSG_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['subject'])")
if [ "$SUBJECT" != "Integration Test Email" ]; then
    echo "ERROR: Expected subject 'Integration Test Email', got '$SUBJECT'"
    exit 1
fi

echo ""
echo "========================================="
echo "  ALL INTEGRATION TESTS PASSED"
echo "========================================="
