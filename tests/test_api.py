"""Testa API:t med en tillfällig, tränad modell."""

import joblib
import pytest
from fastapi.testclient import TestClient

from churn.api import app
from churn.model import trana_och_utvardera


@pytest.fixture(scope="module")
def modellfil(tmp_path_factory):
    # Träna en gång för testfilen, utan att skapa MLflow-körningar.
    modell, _ = trana_och_utvardera()
    fil = tmp_path_factory.mktemp("api-modell") / "modell.joblib"
    joblib.dump(modell, fil)
    return fil


@pytest.fixture
def client(modellfil, monkeypatch):
    # Använd testmodellen i stället för outputs/modell.joblib.
    monkeypatch.setenv("MODEL_PATH", str(modellfil))

    # with-blocket kör API:ts uppstart och laddar modellen.
    with TestClient(app) as testclient:
        yield testclient


@pytest.fixture
def kund():
    return {
        "alder": 45,
        "manader_som_kund": 24,
        "manadskostnad": 299.0,
        "data_gb_per_manad": 15.0,
        "supportarenden_12m": 2,
        "region": "Stockholm",
        "abonnemang": "Standard",
    }


def test_health(client):
    svar = client.get("/health")

    assert svar.status_code == 200
    assert svar.json() == {"status": "ok", "model_loaded": True}


def test_predict(client, kund):
    svar = client.post("/predict", json=kund)

    assert svar.status_code == 200
    assert 0 <= svar.json()["risk"] <= 1


def test_predict_rejects_invalid_age(client, kund):
    kund["alder"] = 17

    svar = client.post("/predict", json=kund)

    assert svar.status_code == 422


def test_startup_rejects_missing_model(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_PATH", str(tmp_path / "saknas.joblib"))

    with pytest.raises(RuntimeError, match="Modellfilen saknas"):
        with TestClient(app):
            pass