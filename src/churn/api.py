"""API som använder den färdigtränade churnmodellen."""

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import joblib
import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from churn.data import FEATURES, skapa_features


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ladda modellen en gång när servern startar.
    modellfil = Path(os.environ.get("MODEL_PATH", "outputs/modell.joblib"))

    if not modellfil.is_file():
        raise RuntimeError(f"Modellfilen saknas: {modellfil}")

    app.state.modell = joblib.load(modellfil)
    yield
    app.state.modell = None


app = FastAPI(title="Saldes churn API", lifespan=lifespan)


class Kund(BaseModel):
    # Avvisa extra fält och ogiltiga tal som NaN och infinity.
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    alder: int = Field(ge=18, le=100)
    manader_som_kund: int = Field(ge=0)
    manadskostnad: float = Field(ge=0)
    data_gb_per_manad: float = Field(ge=0)
    supportarenden_12m: int = Field(ge=0)
    region: str = Field(min_length=1, pattern=r"\S")
    abonnemang: Literal["Bas", "Standard", "Premium"]


class Prognos(BaseModel):
    risk: float = Field(ge=0, le=1)


@app.get("/health")
def health(request: Request):
    """Kontrollera att tjänsten har en laddad modell."""
    if getattr(request.app.state, "modell", None) is None:
        raise HTTPException(status_code=503, detail="Modellen är inte laddad")

    return {"status": "ok", "model_loaded": True}


@app.post("/predict", response_model=Prognos)
def predict(kund: Kund, request: Request):
    """Beräkna churnrisk för en kund."""
    modell = getattr(request.app.state, "modell", None)

    if modell is None:
        raise HTTPException(status_code=503, detail="Modellen är inte laddad")

    # Gör kunduppgifterna till en tabell med en rad.
    kunddata = pd.DataFrame([kund.model_dump()])

    # Samma feature-kod som används under träningen.
    features = skapa_features(kunddata)[FEATURES]

    risk = float(modell.predict_proba(features)[0, 1])
    return Prognos(risk=risk)