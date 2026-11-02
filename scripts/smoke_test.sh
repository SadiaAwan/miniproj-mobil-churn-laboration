#!/usr/bin/env bash

set -euo pipefail

IMAGE="${1:-churn-api:dev}"

echo "=================================="
echo " Starting Docker smoke-test"
echo " Image: $IMAGE"
echo "=================================="

echo "[1/3] Testing model and call list..."

docker run --rm "$IMAGE" python -c '
import csv
import math
import subprocess
from pathlib import Path

output = Path("outputs/ringlista.csv")
output.unlink(missing_ok=True)

subprocess.run(
    ["python", "-m", "churn.score"],
    check=True
)

assert output.is_file(), "Ringlista saknas!"

with output.open(newline="") as file:
    reader = csv.DictReader(file)
    assert reader.fieldnames == ["kund_id", "risk"], \
        f"Fel kolumner: {reader.fieldnames}"
    rows = list(reader)

assert len(rows) == 100, \
    f"Förväntade 100 kunder, fick {len(rows)}"

ids = [row["kund_id"] for row in rows]
assert all(ids), "Tomma kund-ID hittades"
assert len(ids) == len(set(ids)), \
    "Dubbla kund-ID hittades"

risker = [float(row["risk"]) for row in rows]

assert all(
    math.isfinite(risk) and 0 <= risk <= 1
    for risk in risker
), "Ogiltiga riskvärden hittades"

assert risker == sorted(risker, reverse=True), \
    "Ringlistan är inte sorterad efter risk"

print("PASS: 100 giltiga kunder i ringlistan")
'

echo "[2/3] Testing missing model handling..."

if output=$(docker run --rm "$IMAGE" \
    python -m churn.score outputs/missing-model.joblib 2>&1)
then
    echo "FAIL: Missing model was accepted"
    exit 1
fi

if [[ "$output" == *"FEL: hittar inte outputs/missing-model.joblib"* ]]; then
    echo "PASS: Missing model correctly rejected"
else
    echo "FAIL: Unexpected error from container"
    echo "$output"
    exit 1
fi

echo "[3/3] Testing API health and prediction..."

# Starta containern med dess vanliga startkommando: Uvicorn.
CONTAINER_ID=$(docker run -d "$IMAGE")

# Ta alltid bort testcontainern och visa loggar vid fel.
cleanup() {
    result=$?
    trap - EXIT

    if [ "$result" -ne 0 ]; then
        docker logs "$CONTAINER_ID" || true
    fi

    docker rm -f "$CONTAINER_ID" >/dev/null 2>&1 || true
    exit "$result"
}
trap cleanup EXIT

# Testa HTTP inuti containern utan att publicera en port på datorn.
docker exec -i "$CONTAINER_ID" python - <<'PY'
import json
import math
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

base = "http://127.0.0.1:8000"

# Vänta på att API:t startar och modellen laddas.
for attempt in range(30):
    try:
        with urlopen(f"{base}/health", timeout=2) as response:
            assert response.status == 200
            health = json.load(response)

        assert health == {"status": "ok", "model_loaded": True}
        break
    except (URLError, TimeoutError):
        time.sleep(1)
else:
    raise SystemExit("FAIL: API did not become ready")

print("PASS: API health check")

kund = {
    "alder": 45,
    "manader_som_kund": 24,
    "manadskostnad": 299.0,
    "data_gb_per_manad": 15.0,
    "supportarenden_12m": 2,
    "region": "Stockholm",
    "abonnemang": "Standard",
}

request = Request(
    f"{base}/predict",
    data=json.dumps(kund).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)

with urlopen(request, timeout=10) as response:
    assert response.status == 200
    prediction = json.load(response)

risk = prediction["risk"]
assert math.isfinite(risk) and 0 <= risk <= 1

print("PASS: API prediction")
PY

echo "=================================="
echo " ALL SMOKE TESTS PASSED"
echo "=================================="