import logging
import logging.config
import yaml
import os

class ContextFilter(logging.Filter):
    """add batch_id to logs"""
    def __init__(self, batch_id="N/A"):
        super().__init__()
        self.batch_id = batch_id

    def filter(self, record):
        record.batch_id = self.batch_id
        return True

def setup_logging(yaml_path="config/logging.yaml", batch_id="N/A"):
    os.makedirs("logs", exist_ok=True)

    with open(yaml_path, "r") as f:
        config = yaml.safe_load(f)
        logging.config.dictConfig(config)
    
    logger = logging.getLogger()
    context_filter = ContextFilter(batch_id=batch_id)
    for handler in logger.handlers:
        handler.addFilter(context_filter)

    return logger