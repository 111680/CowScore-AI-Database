# CowScore AI backend

FastAPI, SQLAlchemy 2, PostgreSQL and Alembic metadata backend for cattle monitoring. No AI model, veterinary thresholds, image binaries, or real cattle data are included. The API starts without creating tables; use migrations first.

Veterinarian-controlled manual and AI-assisted assessment workflows are documented in [WORKFLOWS.md](WORKFLOWS.md), including credential provisioning, migration, multipart requests, AI-team integration and review transitions. Apply the new additive migration before upgrading the API. Image uploads and BCS/scoring-standard/prediction writes now require individually configured workflow credentials; approval requires a verified veterinarian granted approval permission. Unconfigured credentials fail closed. Existing URLs, read APIs, CSV tools and export/split logic are retained.

## Architecture

Draft scoring standards can have null approval identity/date; their API responses explicitly show `approval_status: draft`. At least one category is always required. Draft standards cannot support approved BCS assessments and are excluded from default training exports. See API.md for a draft 1–5 JSON example with no invented category thresholds.

For an existing database, apply the non-destructive nullable-approval migration without resetting records:

```powershell
.\.runtime\python.exe -m alembic upgrade head
```

Use `.\.venv\Scripts\python.exe` instead if using the normal virtual environment. The initial migration remains unchanged. Existing standards retain their approval evidence. Downgrade refuses to proceed while drafts exist rather than deleting them or fabricating approval.

`app/main.py` exposes REST routes; `schemas.py` validates request/response data; `services.py` checks ownership and scoring standards; `models.py` defines relational constraints; `db.py` configures sessions; `datasets.py` handles atomic imports and grouped exports. Alembic owns schema evolution. Database foreign keys restrict deletion of historical parents. There are no delete endpoints.

One cow has many observations, measurements and assessments. Images and cows are many-to-many through `image_cows`. Assessments and predictions reference that association using a composite foreign key including cow identity. Scoring standards and their permitted categories are configured explicitly. See [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md), [ERD.md](ERD.md), [API.md](API.md) and [INTEGRATION.md](INTEGRATION.md).

## Windows 11 setup (PowerShell)

Install Python 3.12 and Docker Desktop with the WSL2 backend, then start Docker Desktop. Run these commands from this workspace:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

Replace `CHANGE_ME` with a local password in both `POSTGRES_PASSWORD` and `DATABASE_URL`. URL-encode special characters in the database URL. `.env` is ignored by Git. Database credentials in Compose come from that file. For the optional full-stack Compose profile use a URL-safe password, since Compose interpolates it into a URL.

```powershell
docker compose up -d db
docker compose ps
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Keep the server terminal open. In a second PowerShell terminal:

```powershell
Start-Process 'http://127.0.0.1:8000/docs'
Invoke-RestMethod http://127.0.0.1:8000/health
$base = 'http://127.0.0.1:8000'
# Set WORKFLOW_TOKEN to the raw token provisioned for this veterinarian; see WORKFLOWS.md.
$workflowHeaders = @{Authorization="Bearer $env:WORKFLOW_TOKEN"}
$cow = Invoke-RestMethod "$base/cows" -Method Post -ContentType 'application/json' -Body (@{cow_identifier='SYNTHETIC-DEMO-001';notes='Synthetic demonstration only'} | ConvertTo-Json)
$image = Invoke-RestMethod "$base/images" -Method Post -ContentType 'application/json' -Body (@{image_path='original/synthetic-demo.jpg';captured_at='2025-01-01T12:00:00Z';source='synthetic-demo'} | ConvertTo-Json)
$association = Invoke-RestMethod "$base/image-cows" -Method Post -ContentType 'application/json' -Body (@{cow_id=$cow.id;image_id=$image.id;crop_path='cropped/synthetic-demo.jpg'} | ConvertTo-Json)
```

The above paths are metadata examples; no image is created. For real labels register your actual veterinarian-approved standard via `/scoring-standards` and use only its approved categories. The following synthetic configuration and assessment are solely for demonstrating the API in a development database; they do not represent veterinary approval or a real assessment. They remain pending and are excluded from normal exports.

```powershell
$standard = @{name='SYNTHETIC-DEMO-ONLY';approved_by=$null;approved_at=$null;categories=@('Low','Normal','High')}
Invoke-RestMethod "$base/scoring-standards" -Method Post -Headers $workflowHeaders -ContentType 'application/json' -Body ($standard | ConvertTo-Json)
$label = @{cow_id=$cow.id;image_cow_id=$association.id;bcs_category='Normal';scoring_standard='SYNTHETIC-DEMO-ONLY';evaluator='Synthetic demonstration';evaluation_method='manual';evaluation_date='2025-01-02T12:00:00Z';review_status='pending';notes='SYNTHETIC TEST ONLY'}
Invoke-RestMethod "$base/bcs" -Method Post -Headers $workflowHeaders -ContentType 'application/json' -Body ($label | ConvertTo-Json)
.\.venv\Scripts\python.exe -m scripts.export_dataset --seed 42
.\.venv\Scripts\python.exe -m pytest -q
```

Training export writes `dataset/exports/training.csv` plus a manifest. With only the pending demo label, the CSV contains a header only. Do not approve synthetic examples into a real training dataset.

Optional containerized API:

```powershell
docker compose --profile full up --build -d
docker compose logs api
```

## Testing and migrations

Default tests use isolated in-memory SQLite databases with foreign keys enabled. They do not establish PostgreSQL compatibility by themselves. To run the same suite against PostgreSQL, create a **dedicated disposable empty test database** first. The fixture creates and drops all application tables there:

```powershell
$env:TEST_DATABASE_URL = 'postgresql+psycopg://cowscore:YOUR_URL_ENCODED_PASSWORD@localhost:5432/cowscore_test'
.\.venv\Scripts\python.exe -m pytest -q
Remove-Item Env:TEST_DATABASE_URL
```

After model changes, generate and review a new migration:

```powershell
.\.venv\Scripts\python.exe -m alembic revision --autogenerate -m 'describe schema change'
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic check
```

Never rewrite an applied migration. Take and verify backups before production migrations; downgrade removes tables and data. Dependencies have bounded compatible ranges; pin an audited lockfile for a deployed environment.

## HTTP dataset export

`GET /datasets/export` downloads `training.csv` using the existing export/split service. Query parameters default to `seed=42`, `train_frac=0.8`, `val_frac=0.1`. The HTTP endpoint requires `train_frac > 0`, `val_frac >= 0`, and `train_frac + val_frac < 1`; invalid/nonfinite values return 422. Unknown query parameters are rejected. No output path or approval override is accepted. Only approved BCS assessments under standards with recorded veterinary approval are exported. Empty datasets return HTTP 200 with the CSV header only.

Access requires a bearer token. Set a strong, random `DATASET_EXPORT_TOKEN` in your environment or local `.env`, then restart FastAPI. When unset/empty, the endpoint is disabled (503); missing/incorrect tokens return 401. Do not commit or share this token outside authorized dataset users. Swagger exposes the `DatasetExportToken` Authorize option. This credential applies to this dataset endpoint; it does not add authentication to other existing routes. Use TLS and request/concurrency limits when deploying outside localhost.

Example for a server terminal (the generated token stays in that process environment; retain it securely for the authorized client):

```powershell
Set-Location D:\CowScore-AI-Database
$env:DATASET_EXPORT_TOKEN = & .\.runtime\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
.\.runtime\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

For a client terminal, set `DATASET_EXPORT_TOKEN` to the same securely retained token before running:

```powershell
Invoke-WebRequest -UseBasicParsing `
  -Uri 'http://127.0.0.1:8000/datasets/export?seed=42&train_frac=0.8&val_frac=0.1' `
  -Headers @{Authorization="Bearer $env:DATASET_EXPORT_TOKEN"} `
  -OutFile '.\training.csv'
```

Each request generates the CSV and checksum manifest in a unique OS temporary directory. The CSV is streamed as an attachment; `X-Dataset-SHA256` contains its checksum and `Cache-Control: no-store` prevents normal caching. The CSV and manifest are removed after the response, including handled export errors, send errors, and cancellation. Internal temporary paths are never returned. An abrupt process termination may still require OS/operator temporary-file cleanup. Export failures return a generic 503, with diagnostic details restricted to server logs. No schema changes or migrations are required, and the CLI export remains unchanged.

## Image uploads

`POST /images/upload` accepts `multipart/form-data`. Required fields are `file`, `captured_at` (ISO timestamp with timezone), and `source`; optional fields are `camera_angle` and `quality_status` (`unreviewed`, `accepted`, `rejected`). Try it using the file picker in `/docs`. Existing `POST /images` remains the JSON metadata-only endpoint.

Install the updated requirements (`Pillow` and `python-multipart` were added), then restart the server. No database migration is needed for uploads:

```powershell
Set-Location D:\CowScore-AI-Database
.\.runtime\python.exe -m pip install -r requirements.txt
.\.runtime\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Use `.\.venv\Scripts\python.exe` in place of `.\.runtime\python.exe` if using the normal virtual environment. In another PowerShell terminal, upload an actual local image (replace the example file path):

```powershell
curl.exe --fail-with-body -X POST 'http://127.0.0.1:8000/images/upload' `
  -H "Authorization: Bearer $env:WORKFLOW_TOKEN" `
  -F 'file=@C:\Images\cow.jpg;type=image/jpeg' `
  -F 'captured_at=2026-11-22T10:00:00+02:00' `
  -F 'source=field-camera' `
  -F 'camera_angle=rear'
```

Actual file bytes must decode as a single-frame JPEG or PNG and match the `.jpg`, `.jpeg`, or `.png` extension (case insensitive). Supplied MIME type must match, or be `application/octet-stream`/absent. Empty, corrupt, truncated, animated, disguised and oversized files are rejected. Configurable `.env` limits are `MAX_UPLOAD_BYTES=10485760` (10 MiB) and `MAX_IMAGE_PIXELS=20000000`; Pillow also enforces its built-in decompression-bomb limits.

Files are stored unchanged under `STORAGE_ROOT/original/<uuid>.jpg` or `.png`; client filenames are never used as storage paths. Exclusive file creation prevents overwriting existing files. A symlink resolving the original directory outside the configured root is rejected. Keep this directory writable only by trusted service operators. Responses return HTTP 201 with `id`, relative `image_path`, capture/source/quality metadata, `created_at`, detected `image_format`, `width`, `height`, and `size_bytes`. Dimensions and byte size are response metadata, not additional database columns. Image bytes remain on disk, not in PostgreSQL.

File writes and database transactions cannot be one atomic transaction. Handled disk/database failures roll back metadata and remove the file created by that request, including partially written files. An abrupt process/machine crash can still leave an orphan file; operators should reconcile storage against metadata after such failures. Failures return 413 (limits), 415 (unsupported/mismatched format), 422 (invalid content/metadata), 409 (metadata conflict), or 503 (storage/database unavailable).

Multipart parsing happens before endpoint validation and may spool incoming files to temporary disk. For network deployment, set a request-body limit at the reverse proxy (slightly above the allowed file size to account for multipart fields), along with authentication and request limits described below. The upload does not verify that the subject is cattle, perform AI preprocessing/segmentation, or expose a public image-serving route.

## Scope and operations

This backend is intended for local/team integration. Before internet deployment configure the workflow identity registry and approval permissions, TLS, secret management, request limits, logs/monitoring, database backups and a deployment-specific migration job. Workflow credentials are server-provisioned; the API does not independently verify professional licenses. New standard approvals and BCS reviewer identities come from the authenticated principal. Workflow final decisions and finalized legacy assessments cannot be overwritten; detailed revision-level event auditing is not implemented. General metadata/read APIs retain their previous access model; full deployment-wide tenancy/authorization remains a separate concern.

IoT, farm ownership, environmental observations and alerts are intentionally deferred. Add separately indexed observation tables referencing cows/farms through new migrations rather than adding repeated columns or overwriting existing histories.
