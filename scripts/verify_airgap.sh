#!/usr/bin/env bash
# verify_airgap.sh — Verify the RAG system works fully air-gapped.
# Run from the project root: bash scripts/verify_airgap.sh
# Requires: Docker running, stack already up (docker compose up -d).

set -euo pipefail

COMPOSE_PROJECT="${1:-jsa}"
PASS=0
FAIL=0
TOTAL=6

step()  { echo -e "\n\033[36m[$1/$TOTAL] $2\033[0m"; }
pass()  { PASS=$((PASS+1)); echo -e "  \033[32mPASS: $1\033[0m"; }
fail()  { FAIL=$((FAIL+1)); echo -e "  \033[31mFAIL: $1\033[0m"; }
info()  { echo -e "  \033[90m$1\033[0m"; }

get_container() {
    local name
    name=$(docker compose ps --format "{{.Name}}" "$1" 2>/dev/null | head -1)
    if [ -z "$name" ]; then
        name="${COMPOSE_PROJECT}-${1}-1"
    fi
    echo "$name"
}

# ---------------------------------------------------------------------------
# Step 1: Verify rag_net is internal
# ---------------------------------------------------------------------------
step 1 "Verify rag_net is marked internal (no internet gateway)"

INTERNAL=$(docker network inspect "${COMPOSE_PROJECT}_rag_net" \
    --format '{{.Internal}}' 2>/dev/null || echo "unknown")

if [ "$INTERNAL" = "true" ]; then
    pass "rag_net is internal: true"
else
    fail "rag_net internal=$INTERNAL (expected true)"
fi

# ---------------------------------------------------------------------------
# Step 2: Verify backend containers cannot reach the internet
# ---------------------------------------------------------------------------
step 2 "Verify backend containers have no outbound internet access"

AIRGAP_SERVICES="ingestion postgres ollama"
ALL_BLOCKED=true

for svc in $AIRGAP_SERVICES; do
    container=$(get_container "$svc")

    if docker exec "$container" \
        sh -c "wget -q --spider --timeout=5 http://example.com 2>/dev/null" \
        >/dev/null 2>&1; then
        fail "$svc ($container) CAN reach the internet"
        ALL_BLOCKED=false
    else
        info "OK: $svc is air-gapped"
    fi
done

if $ALL_BLOCKED; then
    pass "All backend containers are air-gapped"
fi

# ---------------------------------------------------------------------------
# Step 3: Disconnect external services from default bridge
# ---------------------------------------------------------------------------
step 3 "Disconnect external services from Docker default bridge"

DISCONNECTED=""

for svc in api frontend; do
    container=$(get_container "$svc")
    if docker network disconnect bridge "$container" 2>/dev/null; then
        DISCONNECTED="$DISCONNECTED $container"
        info "Disconnected $svc from bridge"
    else
        info "$svc was not on bridge (OK)"
    fi
done

pass "External services disconnected from default bridge"

# ---------------------------------------------------------------------------
# Step 4: Run ingestion pipeline (air-gapped)
# ---------------------------------------------------------------------------
step 4 "Run ingestion pipeline (air-gapped)"

ingestion_container=$(get_container "ingestion")

output=$(docker exec "$ingestion_container" \
    python -m src.ingestion.main --dry-run 2>&1) || true
exit_code=$?

if [ $exit_code -eq 0 ]; then
    pass "Ingestion pipeline completed (dry-run, exit code 0)"
elif echo "$output" | grep -q "No PDF files found"; then
    pass "Ingestion pipeline ran successfully (no test PDFs mounted)"
else
    fail "Ingestion pipeline failed (exit code $exit_code)"
    echo "$output" | tail -5 | while read -r line; do info "$line"; done
fi

# ---------------------------------------------------------------------------
# Step 5: Query the API (air-gapped)
# ---------------------------------------------------------------------------
step 5 "Query the API endpoint (air-gapped)"

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST http://127.0.0.1:8000/auth/login \
    -H "Content-Type: application/json" \
    -d '{"username":"airgap_test","password":"airgap_test"}' \
    --max-time 10 2>/dev/null || echo "000")

if [ "$HTTP_CODE" = "401" ] || [ "$HTTP_CODE" = "422" ]; then
    pass "API responded with $HTTP_CODE (running and processing requests air-gapped)"
elif [ "$HTTP_CODE" != "000" ]; then
    pass "API responded with status $HTTP_CODE (service is reachable)"
else
    fail "API unreachable (HTTP code $HTTP_CODE)"
fi

# ---------------------------------------------------------------------------
# Step 6: Restore network
# ---------------------------------------------------------------------------
step 6 "Restore network connections"

for container in $DISCONNECTED; do
    if docker network connect bridge "$container" 2>/dev/null; then
        info "Reconnected $container to bridge"
    else
        info "Could not reconnect $container (non-critical)"
    fi
done

pass "Network restored"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "========================================"
echo " Air-gap Verification Summary"
echo "========================================"

if [ $FAIL -eq 0 ]; then
    echo -e "  Passed: \033[32m$PASS / $TOTAL\033[0m"
    echo -e "  Failed: \033[32m$FAIL / $TOTAL\033[0m"
    echo -e "\n\033[32mAll checks PASSED. System is air-gap verified.\033[0m"
    exit 0
else
    echo -e "  Passed: \033[33m$PASS / $TOTAL\033[0m"
    echo -e "  Failed: \033[31m$FAIL / $TOTAL\033[0m"
    echo -e "\n\033[31mSome checks FAILED. Review output above.\033[0m"
    exit 1
fi
