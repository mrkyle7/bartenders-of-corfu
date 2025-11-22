import uvicorn
from app.api import app
import logging
import os

if __name__ == "__main__":
    log_level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s"
    )
    uvicorn.run(app, host="0.0.0.0", port=8000)
