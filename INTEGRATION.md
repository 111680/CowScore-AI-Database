# Integration guide

For authenticated veterinarian image-to-assessment submissions, use the transactional workflow endpoints in [WORKFLOWS.md](WORKFLOWS.md). The guide defines frontend multipart payloads, AI service credential separation, real prediction callbacks and veterinarian approval/correction. No inference model, scheduler or fake production predictions are supplied. Standalone APIs remain, with approval-sensitive writes now authenticated.

## Preprocessing team

Configure `STORAGE_ROOT` (default `dataset`). Put original images in `original/`, crops in `cropped/` and masks in `masks/`. Register paths relative to this root; absolute paths and traversal are rejected. `POST /images` stores metadata without checking file existence; alternatively, `POST /images/upload` validates and stores a JPEG/PNG and registers its metadata in one request. The API does not serve image files. Teammates must share the configured storage root and verify files before training. Upload returns the image ID to use in `/image-cows`; segmentation and crop registration remain separate future integration steps.

Register one image per original file via `/images`. Associate each identified cow through `/image-cows`; there is at most one association per cow in an original image. Save crop and mask paths on the association; bounding boxes use `{x,y,width,height}` pixel coordinates with nonnegative origins and positive dimensions. Use PATCH after segmentation completes. Metadata can precede preprocessing.

## Labeling and model teams

Experimental standards may omit approval evidence or submit both approval fields as null. API responses explicitly return `approval_status: draft`; these standards support pending assessments and experimental predictions but cannot support approved assessments. Default dataset exports require both approved assessments and approved standards. Categories must still contain at least one unique, nonblank item. Use a placeholder such as `Unclassified` while the category rubric is undefined; numeric scale bounds never imply Low/Normal/High thresholds. See API.md for a draft 1–5 example. To record a subsequently approved rubric, register a new versioned standard with genuine approval evidence (there is no standard update endpoint).

Have a veterinarian establish a named/versioned scoring standard, its allowed categories and optional numerical bounds. Register approval identity/date using `/scoring-standards`; the API never invents numerical category thresholds or auto-derives categories. If thresholds are needed, veterinary labelers apply their approved rubric externally and submit both score and category. The backend validates allowed labels and score bounds, not their clinical correspondence. Use a new standard name for a revised rubric.

Manual/veterinary labels go to `/bcs`, initially pending. Reviewers explicitly mark eligible labels approved. Predictions go to `/predictions` with model identity, version and scoring standard. The composite foreign key rejects mismatched cows and associations. Multiple assessments and model versions are supported.

## CSV imports

Invoke from the project root:

```powershell
.\.venv\Scripts\python.exe -m scripts.import_csv cows .\cow_metadata.csv
.\.venv\Scripts\python.exe -m scripts.import_csv images .\image_metadata.csv
.\.venv\Scripts\python.exe -m scripts.import_csv image_cows .\associations.csv
.\.venv\Scripts\python.exe -m scripts.import_csv bcs_records .\labels.csv
.\.venv\Scripts\python.exe -m scripts.import_csv weight_records .\weights.csv
.\.venv\Scripts\python.exe -m scripts.import_csv feeding_records .\feeding.csv
```

CSV headers are request-schema field names plus required `external_key`. Use stable, source-namespaced keys such as `dataset-a:cow:123`; import order is cows, images, associations, labels/measurements. Register scoring standards via the API before labels. Read destination IDs from API responses/lists; foreign-key CSV fields refer to those IDs, not source database IDs. Standard CSV quoting applies (including JSON bounding boxes).

Synthetic format example (not real cattle data):

```csv
external_key,cow_identifier,registration_date,notes
demo:cow:1,SYNTHETIC-CSV-001,2025-01-01,Synthetic test only
```

Supply explicit dates and defaults for stable imports over time. Blank optional cells use defaults/NULL; missing required cells fail validation. Each whole file commits atomically or rolls back with row context. Identical resource/key/content imports skip existing rows; changed content with an existing key is rejected for explicit review. Unique image paths, cow identifiers and image/cow pairs additionally prevent duplicate entities. For API observations, normal POST creates a new history entry; repeatable bulk ingestion must use CSV keys. Reusing the same observation under a different external key is the caller's responsibility.

## Training export

```powershell
.\.venv\Scripts\python.exe -m scripts.export_dataset --output dataset/exports/training.csv --seed 42 --train 0.8 --validation 0.1
```

Only approved manual labels with an image association are selected by default. Labels without a numerical score or without a category retain empty cells; unlabeled images and assessments without images are omitted. Latest eligible assessment per association and standard wins (evaluation date, then ID). Different scoring standards remain separate rows; filter to your intended standard before training.

Cow identities and shared original photographs form connected groups. Groups are shuffled with the supplied seed and allocated train/validation/test in proportions of groups, rounded down for train and validation; test gets the remainder. Ratios of rows/cows may differ and small or strongly connected datasets can have empty splits. Every image/crop for a cow remains in one split; shared originals cannot cross splits. Adding data can change assignments: archive the CSV and manifest with each experiment. The manifest records settings and a file checksum. `--include-unapproved` is an explicit research override that also includes rejected labels; avoid it for normal training.
