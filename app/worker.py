import logging
import time

from app.config import settings
from app.jobs import process_next_job

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s level=%(levelname)s logger=%(name)s message=%(message)s",
)
logger = logging.getLogger("opspilot.worker")


def main() -> None:
    logger.info("worker_started poll_seconds=%s", settings.worker_poll_seconds)
    while True:
        if not process_next_job():
            time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
