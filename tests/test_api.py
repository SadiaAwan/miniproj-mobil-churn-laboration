"""Testa API:t med en tillfällig modell och tillhörande metadata."""

import json
import shutil

import joblib
import pytest
from fastapi.testclient import TestClient

from churn.api import app
from churn.model import trana_och_utvardera

TEST_COMMIT = "a" * 40


@pytest.fixture(scope="module")
def modellfil(tmp_path_factory):
    # Träna en gång utan att skapa MLflow-körningar.
    modell, _ = trana_och_utvardera()
    katalog = tmp_path_factory.mktemp("api-modell")
    fil = katalog / "modell.joblib"
    joblib.dump(modell, fil)

    # Metadata för just testmodellen.
    (katalog / "matvarden.json").write_text(
        json.dumps({"commit": TEST_COMMIT}),
        encoding="utf-8",
    )
    return fil


@pytest.fixture
def client(modellfil, monkeypatch):
    monkeypatch.setenv("MODEL_PATH", str(modellfil))

    # Kör uppstarten och ladda testmodellen.
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


def test_version_uses_model_metadata(client, monkeypatch):
    # API:t ska visa modellens commit, inte processens aktuella commit.
    monkeypatch.setenv("GITHUB_SHA", "b" * 40)

    svar = client.get("/version")

    assert svar.status_code == 200
    assert svar.json() == {"model_version": TEST_COMMIT}


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


def test_startup_rejects_missing_metadata(modellfil, tmp_path, monkeypatch):
    # En modell utan metadata ska inte få en påhittad version.
    fil = tmp_path / "modell.joblib"
    shutil.copyfile(modellfil, fil)
    monkeypatch.setenv("MODEL_PATH", str(fil))

    with pytest.raises(RuntimeError, match="Modellens metadata saknas"):
        with TestClient(app):
            pass


def test_startup_rejects_missing_commit(modellfil, tmp_path, monkeypatch):
    fil = tmp_path / "modell.joblib"
    shutil.copyfile(modellfil, fil)
    (tmp_path / "matvarden.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("MODEL_PATH", str(fil))

    with pytest.raises(RuntimeError, match="saknar en giltig commit"):
        with TestClient(app):
            pass