# CowScore entity relationships

```mermaid
erDiagram
    cows ||--o{ assessment_workflows : tracked
    image_cows ||--o| assessment_workflows : reviewed
    scoring_standards ||--o{ assessment_workflows : governs_workflow
    bcs_records o|--o| assessment_workflows : veterinary_result
    ai_predictions o|--o| assessment_workflows : original_proposal
    assessment_workflows {
        int id PK
        int cow_id FK
        int image_cow_id FK
        string scoring_standard FK
        string mode
        string status
        string created_by
        string request_key
        int bcs_record_id FK
        int prediction_id FK
        string finalized_by
        timestamptz finalized_at
    }
    cows ||--o{ image_cows : appears_in
    images ||--o{ image_cows : contains
    cows ||--o{ bcs_records : assessed
    image_cows o|--o{ bcs_records : supports
    cows ||--o{ weight_records : weighed
    cows ||--o{ feeding_records : fed
    cows ||--o{ health_records : observed
    cows ||--o{ milk_production : produces
    cows ||--o{ ai_predictions : predicted
    image_cows ||--o{ ai_predictions : input
    scoring_standards ||--|{ bcs_categories : configures
    scoring_standards ||--o{ bcs_records : governs
    scoring_standards ||--o{ ai_predictions : interprets
    bcs_categories o|--o{ bcs_records : category
    bcs_categories o|--o{ ai_predictions : category
    cows {
        int id PK
        string cow_identifier UK
        date birth_date
        date registration_date
    }
    images {
        int id PK
        string image_path UK
        timestamptz captured_at
    }
    image_cows {
        int id PK
        int image_id FK
        int cow_id FK
        string crop_path
        string segmentation_mask_path
        json bounding_box
    }
    bcs_records {
        int id PK
        int cow_id FK
        int image_cow_id FK
        decimal bcs_score
        string bcs_category FK
        string scoring_standard FK
        string review_status
        timestamptz evaluation_date
    }
    ai_predictions {
        int id PK
        int cow_id FK
        int image_cow_id FK
        string model_name
        string model_version
        string scoring_standard FK
        decimal confidence_score
        timestamptz prediction_timestamp
    }
    scoring_standards {
        int id PK
        string name UK
        string approved_by
        timestamptz approved_at
    }
    bcs_categories {
        int id PK
        string scoring_standard FK
        string category
    }
    weight_records {
        int id PK
        int cow_id FK
        decimal weight_kg
        timestamptz measurement_timestamp
    }
    feeding_records {
        int id PK
        int cow_id FK
        decimal quantity_offered_kg
        decimal quantity_consumed_kg
        timestamptz feeding_timestamp
    }
    health_records {
        int id PK
        int cow_id FK
        timestamptz observation_date
    }
    milk_production {
        int id PK
        int cow_id FK
        decimal milk_quantity_liters
        timestamptz measurement_timestamp
    }
    import_rows {
        int id PK
        string resource
        string external_key
        string payload_hash
        int record_id
    }
```

`import_rows` is a transactional ingestion receipt with a logical resource-specific record reference. Composite ownership/category foreign keys are described in DATABASE_SCHEMA.md; the diagram abbreviates those pairs.
