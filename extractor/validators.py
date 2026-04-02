"""Security validators for file uploads."""
import os
from django.core.exceptions import ValidationError
from django.conf import settings

# Max file size: 10MB
MAX_FILE_SIZE = 10 * 1024 * 1024

# Allowed MIME types
ALLOWED_MIME_TYPES = [
    'application/pdf',
    'image/jpeg',
    'image/jpg',
    'image/png',
]

# Allowed extensions
ALLOWED_EXTENSIONS = ['.pdf', '.jpg', '.jpeg', '.png']


def validate_file_size(file):
    """Validate file size."""
    if file.size > MAX_FILE_SIZE:
        raise ValidationError(f"File size exceeds {MAX_FILE_SIZE / (1024*1024):.1f}MB limit.")


def validate_file_type(file):
    """Validate file extension and optionally MIME type."""
    ext = os.path.splitext(file.name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationError(f"File type {ext} not allowed. Allowed: {', '.join(ALLOWED_EXTENSIONS)}")

    # MIME check using python-magic if available and libmagic is installed
    try:
        import magic
        mime = magic.Magic(mime=True)
        detected = mime.from_buffer(file.read(1024))
        file.seek(0)
        if detected not in ALLOWED_MIME_TYPES:
            raise ValidationError(f"Invalid MIME type: {detected}")
    except (ImportError, Exception):
        pass  # Skip MIME check if python-magic or libmagic not available


def sanitize_filename(filename):
    """Sanitize filename to prevent path traversal."""
    # Remove path components
    filename = os.path.basename(filename)
    # Remove dangerous characters
    dangerous = ['..', '/', '\\', '\x00']
    for d in dangerous:
        filename = filename.replace(d, '')
    # Limit length
    if len(filename) > 255:
        name, ext = os.path.splitext(filename)
        filename = name[:250] + ext
    return filename

