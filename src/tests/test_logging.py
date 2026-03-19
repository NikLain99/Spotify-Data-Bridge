from src.infrastructure.logging import setup_logging
import uuid
import sys
import os

batch_id = str(uuid.uuid4())
logger = setup_logging(batch_id=batch_id)

logger.info("Test INFO")
logger.warning("Test WARNING ")
logger.error("Test ERROR")