"""Validated binary storage; no image transformation or AI processing."""
from io import BytesIO
from pathlib import Path
from uuid import uuid4
import warnings

from fastapi import HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .db import settings
from .models import Image as ImageRecord
from .schemas import ImageCreate, ImageUploadOut
from .services import create

FORMATS = {'.jpg': 'JPEG', '.jpeg': 'JPEG', '.png': 'PNG'}
MIMES = {'JPEG': 'image/jpeg', 'PNG': 'image/png'}

def store_upload(file: UploadFile, metadata: dict, session, after_create=None):
    extension = Path((file.filename or '').replace('\\', '/')).suffix.lower()
    if extension not in FORMATS:
        raise HTTPException(415, 'Only .jpg, .jpeg and .png files are accepted')
    # Count actual bytes, independently of untrusted Content-Length and MIME headers.
    content = bytearray()
    while chunk := file.file.read(min(65536, settings.max_upload_bytes + 1 - len(content))):
        content.extend(chunk)
        if len(content) > settings.max_upload_bytes:
            raise HTTPException(413, 'Image exceeds MAX_UPLOAD_BYTES')
    if not content:
        raise HTTPException(422, 'Image file is empty')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as image:
                image_format = image.format
                if image_format not in MIMES:
                    raise HTTPException(415, 'Actual image format must be JPEG or PNG')
                if image_format != FORMATS[extension]:
                    raise HTTPException(415, 'Filename extension does not match actual image format')
                if file.content_type not in (None, 'application/octet-stream', MIMES[image_format]):
                    raise HTTPException(415, 'Content-Type does not match actual image format')
                width, height = image.size
                if width * height > settings.max_image_pixels:
                    raise HTTPException(413, 'Image exceeds MAX_IMAGE_PIXELS')
                if getattr(image, 'n_frames', 1) != 1:
                    raise HTTPException(415, 'Animated images are not accepted')
                image.verify()
            # verify checks container integrity; decoding also catches truncated data.
            with Image.open(BytesIO(content)) as image:
                image.load()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise HTTPException(413, 'Image dimensions exceed safe decoding limits') from exc
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
        raise HTTPException(422, 'Invalid or corrupt image content') from exc

    relative = Path('original') / (uuid4().hex + ('.jpg' if image_format == 'JPEG' else '.png'))
    validated = ImageCreate(image_path=relative.as_posix(), **metadata)
    saved = None
    try:
        root = settings.storage_root.resolve()
        directory = (root / 'original').resolve()
        if not directory.is_relative_to(root):
            raise HTTPException(503, 'Upload storage directory is outside STORAGE_ROOT')
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / relative.name
        # Exclusive create never overwrites existing files, even on a UUID collision.
        with destination.open('xb') as stream:
            saved = destination
            stream.write(content)
        record = create(session, ImageRecord, validated.model_dump())
        result = ImageUploadOut.model_validate({
            **validated.model_dump(), 'id': record.id, 'created_at': record.created_at,
            'image_format': image_format, 'width': width, 'height': height,
            'size_bytes': len(content),
        })
        # Workflow callback joins cow/association/assessment inserts to this same
        # transaction and inherits file cleanup on any downstream failure.
        if after_create is not None:
            result = after_create(record)
        session.commit()
        return result
    except Exception as exc:
        try:
            session.rollback()
        finally:
            if saved is not None:
                saved.unlink(missing_ok=True)
        if isinstance(exc, IntegrityError):
            raise HTTPException(409, 'Image metadata conflicts with an existing record') from exc
        if isinstance(exc, (SQLAlchemyError, OSError)):
            raise HTTPException(503, 'Image storage or database is unavailable') from exc
        raise
