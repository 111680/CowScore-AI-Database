"""Atomic CSV import and identity-grouped, reproducible training export."""
import csv
import hashlib
import json
import random
from pathlib import Path
from sqlalchemy import select
from . import models as m, schemas as s
from .services import create

RESOURCES = {
    'cows': (m.Cow, s.CowCreate),
    'images': (m.Image, s.ImageCreate),
    'image_cows': (m.ImageCow, s.ImageCowCreate),
    'bcs_records': (m.BCSRecord, s.BCSCreate),
    'weight_records': (m.WeightRecord, s.WeightCreate),
    'feeding_records': (m.FeedingRecord, s.FeedingCreate),
}

def import_csv(session, resource: str, file: Path):
    """Caller must supply a fresh session. Every row needs a stable external_key.

    Retries with identical content are skipped; changed content is rejected rather
    than silently overwriting historical observations. Whole file rolls back on error.
    """
    model, schema = RESOURCES[resource]
    inserted = skipped = 0
    line = 1
    try:
        with file.open(newline='', encoding='utf-8-sig') as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
                raise ValueError('Missing or duplicate CSV headers')
            if 'external_key' not in reader.fieldnames:
                raise ValueError('external_key column is required')
            for line, row in enumerate(reader, 2):
                if None in row or any(value is None for value in row.values()):
                    raise ValueError('Row does not match CSV headers')
                key = row.pop('external_key').strip()
                if not key or len(key) > 200:
                    raise ValueError('external_key must contain 1 to 200 characters')
                data = {name: value if value.strip() else None for name, value in row.items()}
                if data.get('bounding_box'):
                    data['bounding_box'] = json.loads(data['bounding_box'])
                # Optional blanks use schema defaults. Required blanks remain invalid.
                data = {name: value for name, value in data.items() if value is not None}
                validated = schema.model_validate(data)
                # Omitted dynamic defaults (e.g. registration day) must not change
                # the identity of an unchanged source row on tomorrow's retry.
                digest = hashlib.sha256(validated.model_dump_json(exclude_unset=True).encode()).hexdigest()
                prior = session.scalar(select(m.ImportRow).where(m.ImportRow.resource == resource, m.ImportRow.external_key == key))
                if prior:
                    if prior.payload_hash != digest:
                        raise ValueError(f'Changed content for existing external_key {key}')
                    skipped += 1
                    continue
                obj = create(session, model, validated.model_dump())
                session.add(m.ImportRow(resource=resource, external_key=key, payload_hash=digest, record_id=obj.id))
                session.flush()
                inserted += 1
        session.commit()
    except Exception as exc:
        session.rollback()
        raise ValueError(f'{file}: row {line}: {exc}') from exc
    return {'inserted': inserted, 'skipped': skipped}

def export_dataset(session, output: Path, seed=42, train=0.8, validation=0.1, approved_only=True):
    """Latest eligible manual assessment per association and scoring standard.

    A standard may provide only scores or only categories; missing values stay blank.
    Reproducibility assumes the same database snapshot and Python random algorithm.
    """
    if not (0 <= train <= 1 and 0 <= validation <= 1 and train + validation <= 1):
        raise ValueError('Fractions must be nonnegative and sum to at most one')
    query = (select(m.BCSRecord, m.ImageCow, m.Image, m.Cow)
             .join(m.ImageCow, m.BCSRecord.image_cow_id == m.ImageCow.id)
             .join(m.Image, m.ImageCow.image_id == m.Image.id)
             .join(m.Cow, m.BCSRecord.cow_id == m.Cow.id)
             .order_by(m.BCSRecord.evaluation_date.desc(), m.BCSRecord.id.desc()))
    if approved_only:
        query = query.join(m.ScoringStandard, m.BCSRecord.scoring_standard == m.ScoringStandard.name).where(
            m.BCSRecord.review_status == 'approved',
            m.ScoringStandard.approved_by.is_not(None),
            m.ScoringStandard.approved_at.is_not(None))
    selected, seen = [], set()
    for label, association, image, cow in session.execute(query):
        key = (association.id, label.scoring_standard)
        if key in seen:
            continue
        seen.add(key)
        selected.append((label, association, image, cow))

    # Shared originals (including crops from the same original) are grouped too.
    # This prevents background leakage when a single photo contains several cows.
    parents = {}
    def find(x):
        parents.setdefault(x, x)
        root = x
        while parents[root] != root:
            root = parents[root]
        while parents[x] != x:
            parent = parents[x]
            parents[x] = root
            x = parent
        return root
    for cow_id, image_id in session.execute(select(m.ImageCow.cow_id, m.ImageCow.image_id)):
        a, b = find(('cow', cow_id)), find(('image', image_id))
        parents[a] = b
    groups = {}
    for *_, cow in selected:
        groups.setdefault(find(('cow', cow.id)), set()).add(cow.cow_identifier)
    ordered = sorted(groups, key=lambda key: sorted(groups[key]))
    random.Random(seed).shuffle(ordered)
    n_train, n_val = int(len(ordered) * train), int(len(ordered) * validation)
    split = {key: ('train' if i < n_train else 'validation' if i < n_train + n_val else 'test') for i, key in enumerate(ordered)}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=['image_or_crop_path', 'cow_identifier', 'bcs_score', 'bcs_category', 'scoring_standard', 'dataset_split'])
        writer.writeheader()
        for label, association, image, cow in sorted(selected, key=lambda row: (row[3].cow_identifier, row[1].id, row[0].scoring_standard)):
            writer.writerow(dict(image_or_crop_path=association.crop_path or image.image_path, cow_identifier=cow.cow_identifier, bcs_score=label.bcs_score, bcs_category=label.bcs_category, scoring_standard=label.scoring_standard, dataset_split=split[find(('cow', cow.id))]))
    manifest = {'seed': seed, 'train_fraction': train, 'validation_fraction': validation, 'approved_only': approved_only, 'rows': len(selected), 'cow_count': len({row[3].id for row in selected}), 'connected_groups': len(groups), 'sha256': hashlib.sha256(output.read_bytes()).hexdigest(), 'selection': 'latest eligible label per image_cow and standard', 'grouping': 'cow identity and shared original image; fractions apply to groups, not rows'}
    output.with_suffix(output.suffix + '.manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return manifest
