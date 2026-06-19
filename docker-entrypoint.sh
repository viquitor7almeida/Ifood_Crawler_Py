#!/bin/sh
set -e

echo "========================================="
echo "  iFood Crawler (Python) - Entrypoint"
echo "========================================="
echo "Data: $(date)"
echo "Flaresolverr: ${CRAWLER_FLARESOLVERR_URL:-http://flaresolverr:8191/v1}"
echo "Paralelismo: ${CRAWLER_PARALLELISM:-5}"
echo "========================================="

mkdir -p /app/data /app/output /app/checkpoints /app/cookies

echo "Aguardando Flaresolverr..."
FLARESOLVERR_URL="${CRAWLER_FLARESOLVERR_URL:-http://flaresolverr:8191}"
for i in $(seq 1 30); do
    if curl -s -o /dev/null "$FLARESOLVERR_URL/health" 2>/dev/null; then
        echo "Flaresolverr pronto!"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "AVISO: Flaresolverr nao respondeu apos 30s"
    fi
    sleep 1
done

exec "$@"
