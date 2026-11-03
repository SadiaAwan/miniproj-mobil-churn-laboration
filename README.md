# Mobil churn – Mini-projekt: deployment till Kubernetes

Detta repository är min individuella vidareutveckling av gruppens
mobil-churnlaboration. Grupparbetet innehöll datavalidering,
modellträning, utvärdering och en pipeline för Docker-image.

I mini-projektet har jag lagt till ett API, Kubernetes-manifest,
stöd för AMD64 och ARM64 samt deployment från GitHub Actions
med manuellt produktionsgodkännande.

## Nya implementationer

| Område | Implementation |
|---|---|
| API | FastAPI med `/health`, `/predict` och `/version`. Modellen laddas en gång vid uppstart. |
| API-tester | Kontrollerar health, prediktion, ogiltig ålder, modellversion och saknade modellfiler eller metadata. |
| Docker | Imagen startar API:t och innehåller både modellen och dess metadata. |
| Smoke-tester | Kontrollerar batchfunktionen, saknad modell samt API:ts health och prediktion. |
| Kubernetes | Deployment med två repliker, rolling update, resursgränser och hälsoprober samt en ClusterIP-service. |
| Två miljöer | Utrullningen har verifierats lokalt i kind och i kursens molnkluster. |
| Flera arkitekturer | Imagen byggs för `linux/amd64` och `linux/arm64`. |
| Versionshantering | Imagen taggas med commitens fullständiga SHA. `/version` läser modellens träningscommit från metadata. |
| CI/CD | Godkänd CI följs av deployment från `main`, efter manuellt godkännande i miljön `production`. |
| Uppdatering och rollback | En ändrad modell har rullats ut och återgång till föregående version har verifierats i molnklustret. |

## Filer som hör till mini-projektet

| Fil | Ansvar |
|---|---|
| `src/churn/api.py` | API, modellinläsning och visning av modellversion. |
| `tests/test_api.py` | Tester av API och uppstart. |
| `src/churn/model.py` | Modellträning, metadata och loggning av bland annat parametern `C` i MLflow. |
| `Dockerfile` | Paketerar tjänsten, modellen och metadata. |
| `.dockerignore` | Begränsar byggkontexten och tillåter de modellfiler som behövs. |
| `scripts/smoke_test.sh` | Funktionstester av Docker-imagen. |
| `k8s/deployment.yaml` | Repliker, image, uppdateringsstrategi, resurser, säkerhetsinställningar och prober. |
| `k8s/service.yaml` | ClusterIP-service som kopplar port 80 till API:ts port 8000. |
| `.github/workflows/ci.yml` | Tester, validering, träning, utvärdering, image-publicering och deployment. |

## CI/CD-flöde

Vid push till `main` körs följande:

1. Tester på Python 3.11, 3.12 och 3.13 samt datavalidering med Pandera.
2. Modellträning och uppladdning av modellartefakter.
3. Modellutvärdering mot gränsen ROC AUC ≥ 0,70.
4. Docker-bygge med den godkända modellartefakten.
5. Smoke-tester, bygge för AMD64 och ARM64 samt publicering i GHCR.
6. CI-grind som kontrollerar de obligatoriska jobbens resultat.
7. Väntan på manuellt godkännande för `production`.
8. Deployment till Kubernetes samt kontroll av utrullning, health och prediktion.

Samma godkända modellartefakt används i Docker-bygget.
Modellen tränas inte om under image-bygget eller vid deployment.

Deployment-jobbet körs endast vid push till `main`.
Pull requests, schemalagda körningar och manuella workflow-körningar
startar inte produktionsdeployment i den nuvarande konfigurationen.

### Produktionsgodkännande och klusteråtkomst

GitHub-miljön `production` har obligatoriskt manuellt godkännande
och tillåter deployment från `main`.

Klusteranslutningen lagras som en environment secret med namnet
`KUBE_CONFIG`. Kubeconfig ska inte läggas i repositoryt.

## API

| Metod | Endpoint | Funktion |
|---|---|---|
| GET | `/health` | Kontrollerar att modellen är laddad. |
| POST | `/predict` | Beräknar churnrisk för en kund. |
| GET | `/version` | Visar modellens träningscommit från `matvarden.json`. |
| GET | `/docs` | Interaktiv Swagger-dokumentation. |

Exempel på kunduppgifter för `/predict`:

```json
{
  "alder": 45,
  "manader_som_kund": 24,
  "manadskostnad": 299,
  "data_gb_per_manad": 15,
  "supportarenden_12m": 2,
  "region": "Stockholm",
  "abonnemang": "Standard"
}
```

Svaret innehåller `risk`, ett tal mellan 0 och 1.

`/version` visar `"lokal"` om metadata skapades genom lokal träning
utan `GITHUB_SHA`. Vid träning i GitHub Actions innehåller metadata
workflow-körningens commit-SHA.

## Köra och testa lokalt

Docker Desktop behöver vara igång för Docker-kommandona.

### Träna modellen och köra tester

Kör från repositoryts rot:

```bash
uv sync --locked --extra dev
uv run --locked python -m churn.model
uv run --locked python -m churn.evaluate
uv run --locked --extra dev python -m pytest -q
```

Träningen skapar bland annat:

- `outputs/modell.joblib`
- `outputs/matvarden.json`

API:t behöver båda filerna i samma katalog.

### Bygga och testa Docker-imagen

```bash
docker build -t churn-api:local .
bash scripts/smoke_test.sh churn-api:local
docker run --rm -p 8082:8000 churn-api:local
```

Öppna:

- http://127.0.0.1:8082/health
- http://127.0.0.1:8082/version
- http://127.0.0.1:8082/docs

Stoppa den lokala containern med `Ctrl + C`.

## Kubernetes

Tjänsten har verifierats i två miljöer:

- Lokalt: kind-klustret `churn-local`.
- Molnet: kursklustret med kontext `mlops-ht26`,
  namespace `sadia-awan`.

Manifesten i `k8s/` är för närvarande anpassade för molnklustret.
Deployment-jobbet ersätter manifestets image-tagg med den aktuella
körningens SHA-tagg före applicering.

### Rolling update

Deploymenten använder:

- `replicas: 2`
- `maxSurge: 1`
- `maxUnavailable: 0`

En extra podd kan startas under uppdateringen.
Gamla poddar ersätts successivt när nya blir redo.

Det minskar risken för avbrott, men kräver extra resurser under
övergången och innebär att två versioner tillfälligt kan köras samtidigt.

### Resurser och säkerhet

Varje API-container har:

| Resurs | Request | Limit |
|---|---|---|
| CPU | `50m` | `500m` |
| Minne | `96Mi` | `512Mi` |

Containern kör som användare `10001`, utan root.
Privilege escalation är avstängt, Linux capabilities tas bort
och seccomp-profilen är `RuntimeDefault`.

Startup-, readiness- och liveness-prober anropar `/health`.

### Kontrollera molntjänsten

Kommandona förutsätter att kubeconfig finns i
`$HOME/.kube/mlops-ht26.yaml`.

```bash
kubectl --kubeconfig="$HOME/.kube/mlops-ht26.yaml" \
  --context mlops-ht26 -n sadia-awan \
  get pods -l app=churn-api

kubectl --kubeconfig="$HOME/.kube/mlops-ht26.yaml" \
  --context mlops-ht26 -n sadia-awan \
  rollout status deployment/churn-api --timeout=300s
```

### Nå API:t genom port-forward

```bash
kubectl --kubeconfig="$HOME/.kube/mlops-ht26.yaml" \
  --context mlops-ht26 -n sadia-awan \
  port-forward service/churn-api 8081:80
```

Öppna:

- http://127.0.0.1:8081/health
- http://127.0.0.1:8081/version
- http://127.0.0.1:8081/docs

Anropen går genom port-forward till molnklustret.
`Ctrl + C` stoppar tunneln; tjänsten fortsätter köra i klustret.

Ingress har inte implementerats. Den verifierade åtkomsten använder
ClusterIP och port-forward.

## Demonstrerad modelluppdatering och rollback

Parametern `C` i Logistic Regression ändrades från `1.0` till `0.5`.

| Version | Image-tagg, förkortad | Risk för samma testkund |
|---|---|---|
| Före modelländringen | `cd0bfeb…` | cirka `0.38333` |
| Efter modelländringen | `99bbee7…` | cirka `0.38157` |
| Efter rollback | `cd0bfeb…` | cirka `0.38333` |

Uppdateringen och återgången verifierades med utrullningsstatus,
poddstatus och prediktionsanrop.

Den förändrade prediktionen visar att modellens svar ändrades.
Den är inte i sig ett bevis på förbättrad modellkvalitet.

För att granska revisionshistoriken:

```bash
kubectl --kubeconfig="$HOME/.kube/mlops-ht26.yaml" \
  --context mlops-ht26 -n sadia-awan \
  rollout history deployment/churn-api
```

Vid en framtida rollback ska målrevisionen kontrolleras i den aktuella
historiken. Revisionerna kan förändras när nya versioner rullas ut.

## Verifiering

Vid verifieringen av commit
`442bf1ead263e6706697e2e82642f7e48e1bad97`:

- Passerade samtliga 35 lokala tester.
- Passerade Docker-imagens smoke-tester.
- Passerade CI/CD-körning #13 efter manuellt produktionsgodkännande.
- Returnerade molnets `/version` samma fullständiga commit-SHA.

[Lyckad CI/CD-körning #13](https://github.com/SadiaAwan/miniproj-mobil-churn-laboration/actions/runs/41638792874)

## Drift och avgränsningar

Kubernetes-prober och verifiering efter deployment är implementerade.

Löpande övervakning av svarstider, fel, resursförbrukning,
dataförändringar och modellkvalitet är fortsatt arbete.
Planen för larm, omträning och rollback beskrivs i projektrapporten.

## AI-användning

ChatGPT har använts som stöd för förklaringar, kodförslag,
felsökning och dokumentationsutkast. Ändringar har kontrollerats
genom lokala tester, Docker-tester, GitHub Actions och anrop
till tjänsten i molnklustret.

---

## Dokumentation från den ursprungliga grupplaborationen

Nedan följer dokumentationen som följde med från gruppens repository.
Den beskriver bakgrunden och det ursprungliga arbetet.



# Churnmodellen – Saldes Mobil AB

> *Saldes Mobil AB är ett påhittat företag och all kunddata är fiktiv. Repot är en övning i
> kursen Kontinuerlig integration och leverans (MLOps25, Nackademin).*

## Välkommen till teamet

Hej och välkommen!

Kul att du börjar hos oss som MLOps-ingenjör. Här är bakgrunden till ditt första uppdrag.

Vi tappar kunder. Analysteamet har byggt en modell som förutsäger vilka kunder som riskerar
att säga upp sitt abonnemang. Varje måndag får kundtjänst en **ringlista** med de kunder som
har högst risk, och ringer dem med ett erbjudande.

I dag sköts det mesta för hand. Modellen tränas på en dator här på kontoret, och modellfilen
ligger incheckad i `models/`. Ringlistan gör någon varje måndag morgon med kommandona nedan.
Vi har ett CI-workflow, men det kör allt i ett enda jobb, installerar om alla paket vid
varje push och testar på en annan Python-version än servern som gör ringlistan (3.11).
Sedan förra veckan är det dessutom rött, och ingen har hunnit ta reda på varför.

För två veckor sedan gick det riktigt fel. Kundtjänst fick en ringlista från en modell som
var sämre än den förra. Ingen märkte det förrän säljarna klagade, och ingen kunde säga vilken
commit eller vilken data modellen kom från.

**Ditt uppdrag:** se till att bara en testad modell med känd härkomst kan bli en ringlista.
Jag har skrivit ärenden åt dig, se *Kom igång* nedan.

Två regler:

- Ändra inte modellen, datan eller feature-koden i `src/churn/data.py`. Den sköter
  analysteamet. Ditt arbete är workflows, tester och inställningar i repot.
- Ingen pushar direkt till main när vi väl har skydd på plats. Allt går via pull requests.

Lycka till, och fråga hellre en gång för mycket.

*Teamleaden*

## Kom igång

1. Skapa ditt eget repo från mallen: **Use this template → Create a new repository**.
   Välj ditt eget konto och **Public**.
2. Klona det och skapa ärendena som issues (kräver `gh auth login`):

   ```bash
   git clone https://github.com/<ditt-användarnamn>/<ditt-repo>.git
   cd <ditt-repo>
   bash arenden/skapa.sh
   ```

3. Öppna fliken **Actions** och titta på den första körningen. Börja med ärende F1.

## Så kör man det lokalt med uv

### Installera dependencies
```
uv sync --frozen --extra dev 
```

### Kör den kompletta ML pipelinen
```bash
# Tests
uv run --frozen --no-sync python -m pytest -v 
# Datavalidering
uv run --frozen --no-sync python -m kontroller.validate_data data/kundbas.csv
# Tränar, skriver outputs/modell.joblib och outputs/matvarden.json
uv run --frozen --no-sync python -m churn.model
# Kvalitetsgrind: felkod om ROC AUC är under tröskeln
uv run --frozen --no-sync python -m churn.evaluate
# Skriver outputs/ringlista.csv
uv run --frozen --no-sync python -m churn.score
```


## Vad som finns här

| Sökväg | Innehåll |
| --- | --- |
| `data/kundbas.csv` | 2 000 kunder: ålder, region, abonnemang, kostnad, dataförbrukning, supportärenden och om kunden avslutat (`avslutat`) |
| `src/churn/data.py` | Inläsning och features |
| `src/churn/model.py` | Träning. Skriver modell och mätvärden till `outputs/` |
| `src/churn/evaluate.py` | Kvalitetsgrind på mätvärdena |
| `src/churn/score.py` | Ringlistan |
| `tests/` | Tester på tre nivåer: kod, data och modell |
| `outputs/modell.joblib` |  Modellen som skapas när träningen körs. Sparas inte i Git |
| `arenden/` | Ärendena, och `skapa.sh` som gör dem till issues |
| `.github/workflows/ci.yml` | Vårt CI |

## Modellen och kvalitetskontrollen

Vi använder ROC AUC för att kontrollera modellen. Gränsen är 0,70:
om resultatet är lägre stoppas körningen. Vi kontrollerar också att
resultatet och den valda gränsen är giltiga tal mellan 0 och 1.

Modellen jämförs med en enkel DummyClassifier. Båda använder samma
uppdelning med 25 % testdata, så att jämförelsen görs på samma kunder.

Den gamla modellen i `models/modell.joblib` är borttagen från Git.
När du kör träningskommandot ovan får du en ny modell i
`outputs/modell.joblib`. Resultaten sparas i `outputs/matvarden.json`,
tillsammans med information om vilken kod och data som användes.

Kör sedan utvärderingskommandot ovan för att kontrollera om modellen
blir godkänd. Modellen och resultaten i `outputs/` ignoreras av Git
via `.gitignore` och följer därför inte med i vanliga commits.

## MLflow

MLflow sparar parametrar, mätvärden, commit och datasetets hash
när modellen tränas. Varje körning sparar också en kopia av
`modell.joblib` och `matvarden.json`.

I CI sparas resultaten i ett artifact som heter `mlflow-<commit SHA>`.

### Kör lokalt

Kör från projektets huvudmapp:

```bash
uv sync --locked --extra dev
uv run --locked python -m churn.model
uv run --locked python -m churn.evaluate
uv run --locked mlflow ui --backend-store-uri sqlite:///mlflow.db --port 5001
```

Öppna http://127.0.0.1:5001 och välj `mobil-churn` under
Model training. Stoppa gränssnittet med Ctrl+C.

Lokala resultat sparas i `mlflow.db` och `mlruns/`.
De sparas inte i Git.

### Öppna resultat från CI

Ladda ner artifactet `mlflow-…` från GitHub Actions.
Packa upp ZIP-filen och kopiera `mlflow-tracking.tar.gz` till `outputs/`.

Använd en ny, tom mapp och kör:

```bash
mkdir -p outputs/mlflow-ci
tar -xzf outputs/mlflow-tracking.tar.gz -C outputs/mlflow-ci
uv run --locked python scripts/restore_mlflow.py outputs/mlflow-ci
uv run --locked mlflow ui --backend-store-uri sqlite:///outputs/mlflow-ci/mlflow.db --port 5001
```

Stoppa ett eventuellt öppet MLflow-gränssnitt innan du startar ett nytt
på samma port.

Öppna http://127.0.0.1:5001 och välj `mobil-churn`.
Nu kan du se resultaten från CI utan att träna modellen igen.

Skriptet uppdaterar sökvägarna i den nedladdade databasen och sparar
en backup. Modellen ändras inte. När gränssnittet är stängt kan
den extraherade mappen tas bort.

### Varning vid tester

Testerna kan visa en varning om `noload`, som används internt av
MLflow med SQLAlchemy och är markerat för framtida borttagning.
Vi har lämnat varningen synlig. Alla 28 tester passerar.