"""Träning och utvärdering. Kör: python -m churn.model

Skriver outputs/modell.joblib och outputs/matvarden.json.
"""

import hashlib
import json
import os
from pathlib import Path

import joblib
import mlflow
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from churn.data import (
    DATAKATALOG,
    KATEGORISKA,
    NUMERISKA,
    dela_upp,
    las_data,
    skapa_features,
)

SEED = 42
DATAFIL = "kundbas.csv"


def bygg_modell() -> Pipeline:
    forbehandling = ColumnTransformer(
        [
            (
                "num",
                make_pipeline(
                    SimpleImputer(strategy="median"),
                    StandardScaler(),
                ),
                NUMERISKA,
            ),
            (
                "kat",
                OneHotEncoder(handle_unknown="ignore"),
                KATEGORISKA,
            ),
        ]
    )

    return Pipeline(
        [
            ("forbehandling", forbehandling),
            (
                "klassificerare",
                LogisticRegression(
                    C=0.5,
                    max_iter=1000,
                    random_state=SEED,
                ),
            ),
        ]
    )


def trana_och_utvardera(
    filnamn: str = DATAFIL,
) -> tuple[Pipeline, dict[str, float]]:
    X, y = dela_upp(skapa_features(las_data(filnamn)))

    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.25,
        random_state=SEED,
        stratify=y,
    )

    modell = bygg_modell().fit(X_train, y_train)
    sannolikhet = modell.predict_proba(X_test)[:, 1]

    matvarden = {
        "roc_auc": float(roc_auc_score(y_test, sannolikhet)),
        "accuracy": float(
            accuracy_score(y_test, modell.predict(X_test))
        ),
    }

    return modell, matvarden


def main(utkatalog: Path = Path("outputs")) -> None:
    modell, matvarden = trana_och_utvardera()

    # Spåra vilken commit och datafil modellen kommer från.
    # GITHUB_SHA finns i GitHub Actions. Lokalt används "lokal".
    matvarden["commit"] = os.environ.get("GITHUB_SHA", "lokal")
    matvarden["datafil"] = DATAFIL
    matvarden["data_sha256"] = hashlib.sha256(
        (DATAKATALOG / DATAFIL).read_bytes()
    ).hexdigest()

    utkatalog.mkdir(exist_ok=True)

    joblib.dump(modell, utkatalog / "modell.joblib")

    (utkatalog / "matvarden.json").write_text(
        json.dumps(matvarden, indent=2)
    )

    print(json.dumps(matvarden, indent=2))

    # Spara träningsresultaten i MLflow.
    mlflow.set_tracking_uri(
        os.environ.get(
            "MLFLOW_TRACKING_URI",
            "sqlite:///mlflow.db",
        )
    )
    mlflow.set_experiment("mobil-churn")

    # Varje träning får en separat körning.
    run_name = os.environ.get("MLFLOW_RUN_NAME", "model-local")

    with mlflow.start_run(run_name=run_name):
        klassificerare = modell.named_steps["klassificerare"]

        mlflow.log_params(
            {
                "model_type": "Logistic Regression",
                "random_state": SEED,
                "test_size": 0.25,
                "max_iter": klassificerare.max_iter,
                "C": klassificerare.C,
            }
        )

        mlflow.log_metrics(
            {
                "roc_auc": matvarden["roc_auc"],
                "accuracy": matvarden["accuracy"],
            }
        )

        mlflow.set_tags(
            {
                "commit": matvarden["commit"],
                "datafil": matvarden["datafil"],
                "data_sha256": matvarden["data_sha256"],
            }
        )

        # Spara exakt modell och mätvärden från denna träning.
        mlflow.log_artifact(str(utkatalog / "modell.joblib"))
        mlflow.log_artifact(str(utkatalog / "matvarden.json"))


if __name__ == "__main__":
    main()