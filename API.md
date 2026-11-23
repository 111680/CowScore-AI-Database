# API reference

Veterinary workflows and authorization setup: see WORKFLOWS.md. Workflow tokens identify individual veterinarians or AI services; client reviewer IDs/roles are not trusted. `/images/upload`, standard writes and BCS writes require veterinarian credentials; approving labels/standards requires approval permission. Standalone prediction writes require a veterinarian or AI service. Existing route payloads remain; anonymous approval is intentionally no longer supported.

`POST /scoring-standards` accepts draft standards with `approved_by` and `approved_at` both null or omitted. Both fields must be supplied together for recorded veterinary approval. Responses (POST and GET) include read-only `approval_status`: `draft` or `veterinary_approved`. Status is derived from the approval evidence, never accepted as an input flag. Veterinary credentials are not authenticated by this local API.

Categories remain required: supply at least one nonblank, unique category. Numeric bounds describe the scale only; they do not establish category thresholds. Example experimental 1–5 scale, using an explicit placeholder category pending veterinary definition:

```json
{
  "name": "Experimental BCS 1-5 v1",
  "description": "Draft experimental scale; category rubric awaits veterinary review.",
  "approved_by": null,
  "approved_at": null,
  "minimum_score": 1,
  "maximum_score": 5,
  "categories": ["Unclassified"]
}
```

Pending assessments and AI predictions may reference drafts, but assessment approval is rejected with HTTP 422 until its standard has recorded veterinary approval. Default training exports exclude draft standards even if an assessment was marked approved by an external database writer. `--include-unapproved` explicitly bypasses both review and standard approval filtering.

Swagger: `http://127.0.0.1:8000/docs`. Machine-readable schemas: `/openapi.json`.

| Method | Path | Purpose |
|---|---|---|
| POST / GET | `/cows` | Create / paginated list |
| GET / PATCH | `/cows/{id}` | Retrieve / partial update |
| POST | `/images` | Register metadata only |
| POST | `/images/upload` | Upload JPEG/PNG multipart file and create image metadata |
| POST | `/image-cows` | Associate cow and image |
| PATCH | `/image-cows/{id}` | Add/correct crop, mask, bounding box |
| GET | `/cows/{id}/images` | Image metadata for cow |
| GET | `/cows/{id}/image-cows` | Associations including crop and mask paths |
| POST / GET | `/scoring-standards` | Register / inspect configured standards |
| POST | `/bcs` | Manual/veterinary assessment |
| PATCH | `/bcs/{id}` | Correct score/category or review assessment |
| POST | `/weights`, `/feeding`, `/health-records`, `/milk`, `/predictions` | Add observation or prediction |
| GET | `/cows/{id}/bcs`, `/weights`, `/feeding`, `/health-records`, `/milk`, `/predictions` | Cow history (each suffix under `/cows/{id}`) |
| GET | `/health` | Database connectivity |
| GET | `/datasets/export` | Bearer-authenticated approved dataset CSV download |
| POST | `/assessment-workflows` | Veterinarian multipart image + JSON `StartWorkflow` |
| GET | `/assessment-workflows/{id}` | Authenticated veterinarian/AI workflow and comparison state |
| POST | `/assessment-workflows/{id}/prediction` | AI-service real prediction submission |
| POST | `/assessment-workflows/{id}/review` | Authorized veterinarian approve/correct/reject |

Lists support `offset=0&limit=100` (maximum 1000), ordered newest first for histories. Cow lists are ordered by ID. Writes return 201, reads/updates 200, validation errors 422, missing references 404, duplicate/constraint conflicts 409. All input timestamps require an explicit UTC offset. Unknown input properties are rejected. PATCH distinguishes omitted fields from explicit null; required fields cannot be cleared. BCS cow, image association and scoring standard are fixed after creation.

Example weight request (`POST /weights`):

```json
{"cow_id":1,"weight_kg":420.5,"measurement_timestamp":"2025-01-02T08:00:00+02:00","measurement_context":"before_feeding","measurement_method":"scale","notes":"Synthetic example only"}
```

Example feeding request (`POST /feeding`):

```json
{"cow_id":1,"feeding_timestamp":"2025-01-02T09:00:00+02:00","feed_type":"hay","quantity_offered_kg":5,"quantity_consumed_kg":null,"notes":"Synthetic example only"}
```

Example AI integration request (`POST /predictions`):

```json
{"cow_id":1,"image_cow_id":1,"model_name":"teammate-model","model_version":"v1","predicted_category":"Normal","scoring_standard":"YOUR_APPROVED_STANDARD","confidence_score":0.85,"prediction_timestamp":"2025-01-02T12:00:00Z"}
```

Decimal values serialize as JSON strings to retain precision. AI predictions never become approved manual labels automatically. See README for complete PowerShell cow, image, standard and BCS requests.

Upload request fields: `file` (binary), `captured_at` (timezone-aware timestamp), `source` (required nonblank text up to 120 characters); optional `camera_angle` (nonblank text up to 120 characters), `quality_status` (default `unreviewed`). Swagger exposes a file picker. HTTP 201 response includes all normal image fields plus detected `image_format`, `width`, `height`, and `size_bytes`. The stored path is relative to `STORAGE_ROOT`, e.g. `original/0123456789abcdef0123456789abcdef.jpg`. See README for byte/pixel limits, failure codes, and a Windows `curl.exe` example. No schema migration is needed.

Dataset export: authenticate with `Authorization: Bearer <DATASET_EXPORT_TOKEN>`. The endpoint defaults to `seed=42`, `train_frac=0.8`, `val_frac=0.1`. Train must be positive, validation nonnegative, and their sum strictly less than one (422 otherwise). Veterinary-approved standards and approved labels are mandatory; no override or filesystem-path parameter exists. HTTP 200 is a `text/csv` attachment named `training.csv`, including for an empty dataset (header only). `X-Dataset-SHA256` supplies its checksum. Temporary CSV/manifest artifacts are removed after transfer or failure. HTTP 401 means invalid/missing credentials; 503 means unconfigured access or export failure. Existing CLI behavior is unchanged.
