#!/bin/bash
# Test script for Keycloak authentication
# Usage: ./test_auth.sh

set -e

KEYCLOAK_URL="${KEYCLOAK_URL:-http://localhost:8080}"
REALM="${KEYCLOAK_REALM:-appstore}"
CLIENT_ID="${CLIENT_ID:-appstore-frontend}"
BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"

echo "🔐 Keycloak Authentication Test"
echo "================================"
echo ""
echo "Configuration:"
echo "  Keycloak: $KEYCLOAK_URL"
echo "  Realm: $REALM"
echo "  Client: $CLIENT_ID"
echo "  Backend: $BACKEND_URL"
echo ""

# Check if username and password are provided
if [ -z "$USERNAME" ] || [ -z "$PASSWORD" ]; then
    echo "❌ Error: USERNAME and PASSWORD environment variables required"
    echo ""
    echo "Usage:"
    echo "  export USERNAME=lecturer@example.com"
    echo "  export PASSWORD=your-password"
    echo "  ./test_auth.sh"
    exit 1
fi

echo "👤 Authenticating user: $USERNAME"
echo ""

# Get access token from Keycloak
TOKEN_RESPONSE=$(curl -s -X POST \
  "$KEYCLOAK_URL/realms/$REALM/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=password" \
  -d "client_id=$CLIENT_ID" \
  -d "username=$USERNAME" \
  -d "password=$PASSWORD")

# Extract access token
ACCESS_TOKEN=$(echo "$TOKEN_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('access_token', ''))")

if [ -z "$ACCESS_TOKEN" ]; then
    echo "❌ Failed to obtain access token"
    echo ""
    echo "Response from Keycloak:"
    echo "$TOKEN_RESPONSE" | python3 -m json.tool
    exit 1
fi

echo "✅ Access token obtained successfully"
echo ""

# Decode token (without verification, just for display)
echo "📋 Token Claims:"
echo "$ACCESS_TOKEN" | cut -d. -f2 | base64 -d 2>/dev/null | python3 -m json.tool | head -20
echo "..."
echo ""

# Test protected endpoint
echo "🚀 Testing protected endpoint: POST /api/v1/deployments"
echo ""

DEPLOYMENT_RESPONSE=$(curl -s -X POST "$BACKEND_URL/api/v1/deployments" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "template_version_id": "test-template-123",
    "course_id": "test-course-456",
    "deployment_mode": "per_course",
    "access_types": ["ssh"]
  }')

echo "Response:"
echo "$DEPLOYMENT_RESPONSE" | python3 -m json.tool
echo ""

# Check response status
if echo "$DEPLOYMENT_RESPONSE" | grep -q '"status": "success"'; then
    echo "✅ Deployment created successfully!"
elif echo "$DEPLOYMENT_RESPONSE" | grep -q '"status": "error"'; then
    ERROR_MSG=$(echo "$DEPLOYMENT_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('message', 'Unknown error'))")
    echo "❌ Error: $ERROR_MSG"
else
    echo "⚠️  Unexpected response format"
fi

echo ""
echo "🏁 Test completed"
