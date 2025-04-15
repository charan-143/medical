# migrations package
import logging

# Set up logging for migrations
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Create console handler if one doesn't exist
if not logger.handlers:
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

try:
    from .migrate_uploads import migrate_uploads
    __all__ = ['migrate_uploads']
except ImportError as e:
    logger.error(f"Error importing migration modules: {str(e)}")
    __all__ = []

try:
    from .add_content_hash import add_content_hash_column
    __all__.append('add_content_hash_column')
except ImportError as e:
    logger.error(f"Error importing add_content_hash module: {str(e)}")
