# Veterinary assessment workflows

## Scope and existing records

These workflows reuse `cows`, `images`, `image_cows`, `scoring_standards`, `bcs_records`, and `ai_predictions`. One additive table, `assessment_workflows`, links them and holds pending/review lifecycle state. Existing BCS constraints remain intact: an AI request without a real label is a workflow, not a fabricated BCS record. Historical rows are not rewritten or deleted.

Apply migration `10bc21e4dba4` after `draft_standards_approval` before running the updated server:

```powershell
Set-Location D:\CowScore-AI-Database
.\.runtime\python.exe -m alembic upgrade head
.\.runtime\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Use `.\.venv\Scripts\python.exe` instead if using the normal virtual environment. No database reset is needed. The migration only adds a table, constraints and indexes; downgrade refuses to drop populated workflow audit links.

## Identity and authorization setup

No identity provider or veterinarian user database existed. The minimal implementation uses individually provisioned opaque bearer credentials: a server-managed identity, a SHA-256 digest of a high-entropy token, a role, and a separate approval permission. Clients cannot register themselves, choose a role, supply the recorded reviewer identity, or grant approval rights. The server compares token digests in constant time. Missing configuration fails closed (503); invalid/missing credentials return 401; insufficient role/approval permission returns 403.

Operators must verify the veterinarian's identity and professional authorization **before** provisioning credentials. Do not give an AI process veterinary credentials. Configure `WORKFLOW_CREDENTIALS` as one JSON object in the process environment or ignored `.env`. Example **template**, replacing each digest before use:

```dotenv
WORKFLOW_CREDENTIALS={"clinic:vet-001":{"token_sha256":"<64-character lowercase SHA256 digest>","role":"veterinarian","can_approve":true},"clinic:trainee-002":{"token_sha256":"<different SHA256 digest>","role":"veterinarian","can_approve":false},"integration:ai-worker":{"token_sha256":"<another SHA256 digest>","role":"ai_service","can_approve":false}}
```

To generate a credential locally, run the following in a private operator terminal. It displays sensitive credential material for secure delivery to that single identity; never commit the output or put it in application logs:

```powershell
.\.runtime\python.exe -c "import secrets,hashlib; token=secrets.token_urlsafe(32); print('TOKEN:',token); print('SHA256:',hashlib.sha256(token.encode()).hexdigest())"
```

Store only the digest in `WORKFLOW_CREDENTIALS`. Deliver the token through a secure channel. Restart workers after provisioning, revoking/removing, or rotating credentials. Subject identifiers are stable audit identities: do not reuse one person's subject for another person. There are no default credentials, self-service login, token issuance, password recovery, automatic expiration or license verification. An existing OIDC/session provider can later replace the `authenticate` dependency while preserving the `Principal` contract. For external deployment use TLS, protected secret configuration, request limits, and an authenticated frontend/backend session; do not embed long-lived veterinary credentials in public JavaScript bundles. The credential grants access across this deployment's herd, not per-farm tenancy.

Swagger `/docs` exposes the `WorkflowCredentials` authorization scheme. `DatasetExportToken` remains separate. Legacy read routes and general cow/measurement metadata APIs retain their previous access model; this is not a blanket authorization retrofit for every route.

## Endpoints

| Method | Path | Authorization and purpose |
|---|---|---|
| POST | `/assessment-workflows` | Veterinarian; multipart image plus JSON metadata; starts manual or AI-assisted workflow atomically |
| GET | `/assessment-workflows/{id}` | Veterinarian or AI service; retrieve state, image/cow IDs, original prediction and final assessment |
| POST | `/assessment-workflows/{id}/prediction` | AI service only; store one real prediction against a pending AI workflow |
| POST | `/assessment-workflows/{id}/review` | Veterinarian with `can_approve=true`; approve, correct or reject exactly once |

Responses include `id` (workflow ID), `cow_id`, `image_id`, `image_cow_id`, `image_path`, `bcs_record_id`, `prediction_id`, `status`, `review_status`, `inference_status`, creator/request key, finalizer/time, review notes, nested `assessment`, and nested `prediction`. AI-pending responses have null BCS/prediction IDs until those records actually exist. Numeric JSON output is decimal text as in the existing API.

## Frontend: upload and manual assessment

Let the veterinarian select an image locally, choose an existing cow via `GET /cows` or fill new-cow fields, select a standard using `GET /scoring-standards`, then submit everything together. This avoids leaving a separate staged upload if assessment validation fails. Send multipart fields `file` and `payload`; `payload` is a JSON string. JPEG/PNG validation, byte/pixel limits, unique filenames and safe storage paths reuse the existing upload service.

Example `payload` for an **illustrative** score; the standard must actually exist with veterinarian-established bounds/categories:

```json
{
  "mode": "manual",
  "request_key": "frontend-generated-unique-request-id",
  "cow_id": 1,
  "image": {
    "captured_at": "2026-11-23T10:00:00+02:00",
    "source": "clinic-camera",
    "camera_angle": "rear"
  },
  "scoring_standard": "YOUR_REGISTERED_STANDARD",
  "bcs_score": 3,
  "notes": "Clinician observation"
}
```

Alternatively omit `cow_id` and supply `"new_cow": {"cow_identifier": "YOUR_COW_IDENTIFIER"}` plus optional existing cow-profile fields. Exactly one selection is required. No client filesystem path, evaluator, approval flag or role is accepted. Categories are optional for numeric labels; when supplied they must belong to the selected standard. No category is inferred from a numerical score, and no clinical score thresholds are bundled.

Example browser integration using the authorized veterinarian session's token:

```javascript
const form = new FormData();
form.append('file', selectedFile);
form.append('payload', JSON.stringify(payload));
const response = await fetch('/assessment-workflows', {
  method: 'POST', headers: {Authorization: `Bearer ${authorizedToken}`}, body: form
}); // Do not manually set Content-Type: the browser supplies its multipart boundary.
```

A manual assessment is approved immediately **only** when the authenticated veterinarian has approval permission and the selected standard has both approval fields populated. Otherwise it is saved pending. Its BCS evaluator and evaluation time come from server identity/time. Standard bounds and allowed categories use existing validation. Draft standards cannot be finalized. Standards have no public edit/promotion endpoint; if the rubric changes, register a new approved version and start a new workflow rather than silently relabeling prior observations.

## AI team: real inference integration

Start with `"mode": "ai"` and omit BCS score/category. The backend saves the image, cow association and pending workflow, returning `inference_status: awaiting_prediction`. It does not invoke a model, enqueue fabricated work, or create a placeholder prediction. A real AI worker/scheduler must receive the returned workflow ID from your integration. There is currently no automatic scheduler, polling queue endpoint, public file-serving endpoint or model connection.

With the AI service credential, fetch the workflow and read the original file from the team's trusted shared `STORAGE_ROOT` using its relative `image_path` (or arrange a private image transport). Then submit the actual model output:

```http
POST /assessment-workflows/123/prediction
Authorization: Bearer <AI_SERVICE_TOKEN>
Content-Type: application/json
```

```json
{
  "model_name": "YOUR_REAL_MODEL_NAME",
  "model_version": "YOUR_REAL_MODEL_VERSION",
  "predicted_bcs_score": 3,
  "confidence_score": 0.85,
  "prediction_timestamp": "2026-11-23T08:00:00Z"
}
```

This is a contract example, not an actual prediction. Send the output of your real model; omit confidence/category when unavailable. Cow, association and standard are derived server-side from the workflow. The original prediction is stored separately in `ai_predictions`. It does not approve a label or enter normal training exports. One accepted prediction per workflow is supported in this initial version; duplicate delivery returns 409 and GET retrieves the accepted result. Preserve additional model experiments through existing standalone prediction storage against non-workflow associations or a future versioned workflow extension.

The frontend can poll GET by workflow ID to show the prediction next to veterinarian entry fields. Do not expose the AI service credential to the frontend.

## Review and transitions

Send one of these JSON bodies to `/assessment-workflows/{id}/review` using an approving veterinarian's credential:

```json
{"action": "approve"}
```

```json
{"action": "correct", "bcs_score": 3.5, "notes": "Veterinarian correction"}
```

```json
{"action": "reject", "notes": "Image/assessment unsuitable"}
```

Corrections require an explicit numeric score, checked against the selected standard. Optional category must be supplied explicitly if desired; omission leaves it null, preventing a retained AI category from falsely implying a veterinary threshold mapping. Approve accepts the stored proposal unchanged. AI approval/correction requires an actual stored prediction; until one exists the workflow stays pending (409). Rejection can occur before inference.

| Starting state | Action/event | New workflow state | BCS result |
|---|---|---|---|
| New manual | Authorized approver + approved standard | approved | approved veterinary record |
| New manual | Limited veterinarian or draft standard | pending | pending veterinary record |
| New AI | Upload | pending | no BCS record |
| Pending AI | Real prediction delivery | pending | prediction only, separate table |
| Pending | Approve with approved standard | approved | approved veterinary record |
| Pending | Correct with approved standard | corrected | approved veterinary record with corrected value |
| Pending | Reject | rejected | pending manual label rejected; AI workflow creates no BCS label |

All terminal states are immutable through the workflow API. Subsequent review/prediction calls return 409. On PostgreSQL, review and prediction delivery lock the workflow row and recheck pending state within the transaction. Unique constraints enforce request-key, association, final-label and prediction links. The original AI record is retained unchanged for comparison. The correcting/finalizing veterinarian and time are recorded on the workflow and approved BCS record. The initial version records one final decision, not a full event log of every pending edit.

Use a stable `request_key` per submission attempt. Duplicate creator/key returns 409 with `workflow_id` to retrieve the existing result; do not generate a different key to retry a timed-out submission. Separate intentional observations use different keys.

## Legacy API compatibility and export integrity

Existing URLs and payloads remain. The necessary security changes are:

- `/images/upload` now requires veterinarian authentication.
- `POST /scoring-standards` requires a veterinarian; recording approval additionally requires approval permission. Supplied approval identity/time are replaced with server identity/time; both-null drafts stay drafts.
- `POST /bcs` and `PATCH /bcs/{id}` require a veterinarian. Approval requires approval permission. Client evaluator/time/method cannot impersonate the recorded reviewer; server values are used. Finalized records cannot be overwritten or reapproved.
- `POST /predictions` requires an authenticated veterinarian or AI service for existing standalone prediction integrations.
- Workflow-linked labels/predictions must use workflow endpoints, preventing legacy APIs from bypassing review. Workflow image associations are immutable through generic PATCH.

CLI CSV import remains a trusted local operator tool, not an anonymous HTTP path. Direct SQL and operator tools must be restricted to trusted staff. Existing historical records and clinical approval evidence are not reclassified by this change. Existing CSV export selection and cow/shared-original split logic are unchanged: pending/rejected labels and draft standards are excluded; workflow `corrected` maps to approved BCS review status and therefore exports the final veterinarian value, never the AI prediction.

## Transactions and remaining deployment setup

The workflow joins cow creation, image metadata, association, manual BCS record and workflow into the upload transaction. Any handled failure rolls back new database rows and removes the new upload, including partial writes. Database failures return 503; conflicts return 409. A process crash can still leave a file orphan since a filesystem and PostgreSQL do not share a transaction; maintain operational reconciliation/backups. Existing files and data are never deleted on request rollback.

Remaining setup: apply the additive migration, provision verified identities/approval permissions, register genuine scoring standards/categories, and integrate the actual AI inference service plus private image delivery/job dispatch. Live PostgreSQL/Docker and concurrent-worker behavior must be verified in the deployment environment; SQLite tests verify logic and migration shape, not PostgreSQL row-lock behavior.

## Implementation file inventory

New files: `app/auth.py`, `app/workflow_schemas.py`, `app/workflows.py`, `app/workflow_routes.py`, `tests/test_workflows.py`, `alembic/versions/10bc21e4dba4_add_veterinary_assessment_workflows.py`, and `WORKFLOWS.md`.

Modified code/configuration: `app/db.py` (credential configuration), `app/models.py` (workflow links), `app/uploads.py` (transaction callback), `app/schemas.py` (rebuild ORM response schemas), `app/main.py` (routes/legacy security), `.env.example` (empty fail-closed credential registry), and `docker-compose.yml` (pass local environment configuration to the API container).

Modified tests: `tests/conftest.py` (synthetic authenticated identities), `tests/test_dataset_routes.py` (authenticated fixture setup while preserving separate export credentials), and `tests/test_migrations.py` (data-preserving workflow migration verification).

Modified documentation: `README.md`, `API.md`, `INTEGRATION.md`, `DATABASE_SCHEMA.md`, `ERD.md`, and `TEST_REPORT.md`. Existing applied migrations, `.env`, export/splitting logic, and database records were not modified.
