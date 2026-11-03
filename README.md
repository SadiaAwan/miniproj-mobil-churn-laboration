# Mobil churn – Mini-projekt: deployment till Kubernetes

Detta repository är min individuella vidareutveckling av gruppens
mobil-churnlaboration. Grupparbetet innehöll datavalidering,
modellträning, utvärdering och en pipeline för Docker-image.

I mini-projektet har jag lagt till ett API, Kubernetes-manifest,
stöd för AMD64 och ARM64 samt deployment från GitHub Actions
med manuellt produktionsgodkännande.

CI och produktionsdeployment ligger i två separata workflows:
**CI** och **Deploy Production**.

## Nya implementationer

| Område | Implementation |
|---|---|
| API | FastAPI med `/health`, `/predict` och `/version`. Modellen laddas en gång vid uppstart. |
| API-tester | Kontrollerar health, prediktion, ogiltig ålder, modellversion och saknade modellfiler eller metadata. |
| Docker | Imagen startar API:t och innehåller modellen och dess metadata. |
| Smoke-tester | Kontrollerar batchfunktionen, saknad modell samt API:ts health och prediktion. |
| Kubernetes | Deployment med två repliker, rolling update, resursgränser, hälsoprober och en ClusterIP-service. |
| Två miljöer | Tjänsten har verifierats lokalt i kind och i kursens molnkluster. |
| Flera arkitekturer | Imagen byggs för `linux/amd64` och `linux/arm64`. |
| Versionshantering | Imagen taggas med commitens fullständiga SHA. `/version` läser modellens träningscommit från metadata. |
| CI | Tester, datavalidering, träning, utvärdering, Docker-bygge och publicering i GHCR. |
| Deploy Production | Separat workflow som startar efter lyckad CI från en push till `main` och kräver produktionsgodkännande. |
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
| `.github/workflows/ci.yml` | Tester, datavalidering, träning, utvärdering, Docker-bygge och image-publicering. |
| `.github/workflows/deploy-production.yml` | Produktionsgodkännande, deployment och verifiering i molnklustret. |

## CI och Deploy Production

### CI

Vid push till `main` kör CI följande:

1. Tester på Python 3.11, 3.12 och 3.13 samt datavalidering med Pandera.
2. Modellträning och uppladdning av modellartefakter.
3. Modellutvärdering mot gränsen ROC AUC ≥ 0,70.
4. Docker-bygge med den godkända modellartefakten.
5. Smoke-tester, bygge för AMD64 och ARM64 samt publicering i GHCR.
6. Kontroll av den publicerade AMD64-imagen.
7. CI-grind som kontrollerar de obligatoriska jobbens resultat.

Ringlistan genereras i ett separat jobb efter modellutvärderingen.

Samma modellartefakt som klarat utvärderingen används i Docker-bygget.
Modellen tränas inte om under image-bygget eller vid deployment.

CI kan även köras för pull requests, enligt schema och genom
`Run workflow`. Publicering av image sker endast vid push till `main`.

### Deploy Production

Produktionsdeployment ligger i ett eget workflow:
`.github/workflows/deploy-production.yml`.

Det visas som **Deploy Production** i GitHub Actions och startas
genom `workflow_run` när CI har avslutats.

Deployment-jobbet tillåts endast när:

- CI-körningen har resultatet `success`.
- CI startades av en `push`.
- Grenen är `main`.
- Körningen kommer från detta repository.

Workflowet väntar sedan på manuellt godkännande i miljön `production`.

Efter godkännandet:

1. Checkas den commit som klarade CI ut.
2. Installeras kubectl och dess kontrollsumma verifieras.
3. Konfigureras klusteråtkomsten.
4. Väljs imagen med samma SHA som den godkända CI-körningen.
5. Appliceras Kubernetesmanifesten.
6. Kontrolleras att rolling update har slutförts och rätt image används.
7. Verifieras `/health` och `/predict` genom HTTP-anrop.
8. Tas den tillfälliga kubeconfig-filen bort.

SHA hämtas från `github.event.workflow_run.head_sha`.
Det kopplar deployment till den commit som klarade CI.

Pull requests, schemalagda CI-körningar och manuellt startade
CI-körningar får inte starta produktionsjobbet med dessa villkor.

Det separata deployment-workflowet har ingen egen
`Run workflow`-knapp i den nuvarande konfigurationen.

### Produktionsgodkännande och klusteråtkomst

GitHub-miljön `production` har obligatoriskt manuellt godkännande
och tillåter deployment från `main`.

Klusteranslutningen lagras som en environment secret med namnet
`KUBE_CONFIG`. Kubeconfig ska inte läggas i repositoryt.

Produktionsdeployment körs en åt gången genom en gemensam
concurrency-grupp.

Även en push som endast ändrar README startar fullständig CI
och därefter en begäran om produktionsgodkännande med den
nuvarande konfigurationen.

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
CI-körningens commit-SHA.

API:t läser versionen från metadata som följer med modellen.

## Köra och testa lokalt

Kör kommandona från repositoryts rot.

Docker Desktop behöver vara igång för Docker-kommandona.

### Installera beroenden, träna och testa

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
Deploy Production ersätter manifestets image-tagg med SHA-taggen
från den godkända CI-körningen före applicering.

### Rolling update

Deploymenten använder:

- `replicas: 2`
- `maxSurge: 1`
- `maxUnavailable: 0`

En extra podd kan startas under uppdateringen.
Gamla poddar ersätts successivt när nya blir redo.

Det minskar risken för avbrott, men kräver extra resurser under
övergången och innebär att två versioner tillfälligt kan köras samtidigt.
Inställningarna garanterar inte tillgänglighet vid alla typer av fel.

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

Detta var en tidigare demonstration. Senare versioner har därefter
rullats ut genom GitHub Actions.

För att granska revisionshistoriken:

```bash
kubectl --kubeconfig="$HOME/.kube/mlops-ht26.yaml" \
  --context mlops-ht26 -n sadia-awan \
  rollout history deployment/churn-api
```

Vid en framtida rollback ska målrevisionen kontrolleras i den aktuella
historiken. Revisionerna kan förändras när nya versioner rullas ut.

Rollback sker manuellt. Automatisk rollback vid misslyckad
deployment är inte implementerad.

## Verifiering

### API och modellversion

Vid verifieringen av commit
`442bf1ead263e6706697e2e82642f7e48e1bad97`:

- Passerade samtliga 35 lokala tester.
- Passerade Docker-imagens smoke-tester.
- Passerade den då sammanhållna CI/CD-körningen #13 efter
  manuellt produktionsgodkännande.
- Returnerade molnets `/version` samma fullständiga commit-SHA.

[Historisk CI/CD-körning #13](https://github.com/SadiaAwan/miniproj-mobil-churn-laboration/actions/runs/41638792874)

### Separata workflows

Uppdelningen av CI och deployment verifierades för commit `2a293d1`:

- **CI #15:** Success.
- **Deploy Production #1:** Success efter manuellt godkännande.
- **Deploy approved image:** passerade.
- **Verify health and prediction:** passerade.

Skärmbilder dokumenterar CI-resultatet, produktionsgodkännandet
och den lyckade deploymenten.

Länkar till respektive workflows:

- [CI](https://github.com/SadiaAwan/miniproj-mobil-churn-laboration/actions/workflows/ci.yml)
- [Deploy Production](https://github.com/SadiaAwan/miniproj-mobil-churn-laboration/actions/workflows/deploy-production.yml)

Körningsnummer ovan avser dokumenterade verifieringar och behöver
inte vara de senaste körningarna efter framtida ändringar.

## Drift och avgränsningar

Kubernetes-prober och verifiering efter deployment är implementerade.

Löpande övervakning av svarstider, fel, resursförbrukning,
dataförändringar och modellkvalitet är fortsatt arbete.

Planen är att:

- Följa API-fel, svarstider, poddstatus och resursförbrukning.
- Validera inkommande data och jämföra dess fördelningar med träningsdata.
- Följa modellkvalitet när verkliga churnutfall finns tillgängliga.
- Utreda larm och vid behov omträna eller återställa en tidigare version.

Pandera kontrollerar schema och datakvalitetsregler.
Övervakning av datafördelningar behöver kompletterande kontroller.

Planen för drift beskrivs även i projektrapporten.

## AI-användning

ChatGPT har använts som stöd för förklaringar, kodförslag,
felsökning och dokumentationsutkast.

Ändringar har kontrollerats genom lokala tester, Docker-tester,
GitHub Actions och anrop till tjänsten i molnklustret.

## Repository

[Individuell fork](https://github.com/SadiaAwan/miniproj-mobil-churn-laboration)

---

## Bakgrund från den ursprungliga grupplaborationen

Följande avsnitt beskriver den ursprungliga uppgiften och grupparbetet.
Uppgiftens startläge och arbetsregler är historisk bakgrund.
Den aktuella mini-projektlösningen beskrivs ovan.

### Churnmodellen – Saldes Mobil AB

> Saldes Mobil AB är ett påhittat företag och all kunddata är fiktiv.
> Projektet är en övning i kursen Kontinuerlig integration och leverans,
> MLOps25, Nackademin.

### Ursprungligt uppdrag

Analysteamet hade byggt en modell som förutsäger vilka kunder som
riskerar att säga upp sitt abonnemang. Kundtjänst skulle varje måndag
få en ringlista med kunderna med högst risk.

I uppgiftens startläge sköttes mycket manuellt. Modellen tränades på
en lokal dator, modellfilen låg i `models/` och CI körde allt i ett
enda jobb. Det saknades tillräcklig kontroll av modellkvalitet och
spårbarhet till kod och data.

Gruppens uppdrag var att säkerställa att endast en testad modell
med känd härkomst kunde användas för att skapa ringlistan.

Ursprungsuppgiften angav att modell, data och feature-kod skulle
hanteras av analysteamet och att gruppens ändringar skulle gå
genom pull requests när skyddet av main var på plats.

I det senare individuella mini-projektet ändrades modellparametern
`C` för att demonstrera en ny modellversion och rollback.

### Ursprunglig uppstart från mallen

Dessa steg hör till den ursprungliga grupplaborationen.
De ska inte köras för att fortsätta arbeta i en befintlig klon.

1. Skapa ett publikt repository från mallen med
   **Use this template → Create a new repository**.
2. Klona repositoryt och skapa uppgiftens issues:

   ```bash
   git clone https://github.com/<ditt-användarnamn>/<ditt-repo>.git
   cd <ditt-repo>
   bash arenden/skapa.sh
   ```

   Skriptet kräver autentisering med GitHub CLI, `gh auth login`.

3. Öppna Actions och börja med ärende F1.

### Köra ML-pipelinen lokalt med uv

Installera beroenden:

```bash
uv sync --frozen --extra dev
```

Kör tester, datavalidering, träning, utvärdering och ringlista:

```bash
# Tester
uv run --frozen --no-sync python -m pytest -v

# Datavalidering
uv run --frozen --no-sync python -m kontroller.validate_data data/kundbas.csv

# Träning: skapar outputs/modell.joblib och outputs/matvarden.json
uv run --frozen --no-sync python -m churn.model

# Kvalitetsgrind: felkod om modellen inte klarar utvärderingen
uv run --frozen --no-sync python -m churn.evaluate

# Skapar outputs/ringlista.csv
uv run --frozen --no-sync python -m churn.score
```

### Filer från grupplaborationen

| Sökväg | Innehåll |
|---|---|
| `data/kundbas.csv` | 2 000 fiktiva kunder med kunduppgifter och utfallet `avslutat`. |
| `src/churn/data.py` | Inläsning och features. |
| `src/churn/model.py` | Träning som skriver modell och mätvärden till `outputs/`. |
| `src/churn/evaluate.py` | Kvalitetsgrind på modellens mätvärden. |
| `src/churn/score.py` | Genererar ringlistan. |
| `kontroller/` | Datavalidering med Pandera. |
| `tests/` | Tester av kod, data och modell, senare utökade med API-tester. |
| `outputs/modell.joblib` | Modellen som skapas vid träning. Sparas inte i Git. |
| `arenden/` | Uppgiftens ärenden och skript för att skapa issues. |
| `.github/workflows/ci.yml` | CI-workflowet. |

### Modellen och kvalitetskontrollen

ROC AUC används för att kontrollera modellen. Gränsen är 0,70:
om resultatet är lägre stoppas körningen.

Kontrollen verifierar också att resultatet och den valda gränsen
är giltiga tal mellan 0 och 1.

Modellen jämförs med en enkel DummyClassifier. Båda använder samma
uppdelning med 25 % testdata så att jämförelsen görs på samma kunder.

Den gamla modellen i `models/modell.joblib` togs bort från Git.
Träningen skapar en ny modell i `outputs/modell.joblib`.

Resultaten sparas i `outputs/matvarden.json` tillsammans med
information om vilken kod och data som användes.

Modellen och resultaten i `outputs/` ignoreras av Git via
`.gitignore` och följer därför inte med i vanliga commits.

### MLflow

MLflow sparar parametrar, mätvärden, commit och datasetets hash
när modellen tränas. Varje körning sparar också en kopia av
`modell.joblib` och `matvarden.json`.

I CI sparas resultaten i ett artifact som heter `mlflow-<commit SHA>`.

#### Köra MLflow lokalt

Kör från projektets huvudmapp:

```bash
uv sync --locked --extra dev
uv run --locked python -m churn.model
uv run --locked python -m churn.evaluate
uv run --locked mlflow ui --backend-store-uri sqlite:///mlflow.db --port 5001
```

Öppna http://127.0.0.1:5001 och välj experimentet `mobil-churn`.

Stoppa gränssnittet med `Ctrl + C`.

Lokala resultat sparas i `mlflow.db` och `mlruns/`.
De sparas inte i Git.

#### Öppna MLflow-resultat från CI

Ladda ner artifactet `mlflow-…` från GitHub Actions.
Packa upp ZIP-filen och kopiera `mlflow-tracking.tar.gz` till `outputs/`.

Använd en ny, tom målmapp och kör:

```bash
mkdir -p outputs/mlflow-ci
tar -xzf outputs/mlflow-tracking.tar.gz -C outputs/mlflow-ci
uv run --locked python scripts/restore_mlflow.py outputs/mlflow-ci
uv run --locked mlflow ui --backend-store-uri sqlite:///outputs/mlflow-ci/mlflow.db --port 5001
```

Stoppa ett eventuellt öppet MLflow-gränssnitt innan ett nytt startas
på samma port.

Öppna http://127.0.0.1:5001 och välj `mobil-churn`.
Resultaten från CI kan då granskas utan att modellen tränas igen.

Skriptet uppdaterar sökvägarna i den nedladdade databasen och sparar
en backup. Modellen ändras inte.

När gränssnittet är stängt kan den extraherade mappen tas bort.

#### Varningar vid tester

Tester har visat en varning om `noload`, som används internt av
MLflow med SQLAlchemy och är markerat för framtida borttagning.

Vid den dokumenterade lokala API-verifieringen passerade alla
35 tester, med två deprecationsvarningar.