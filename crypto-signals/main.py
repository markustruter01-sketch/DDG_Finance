import time
import logging
from config import (
    LISTING_POLL_INTERVAL, DEPEG_POLL_INTERVAL, MEMECOIN_POLL_INTERVAL,
    EVENT_POLL_INTERVAL, PRICE_CACHE_INTERVAL, LOOP_SLEEP_SECONDS, SERVICE_NAME,
)

logger = logging.getLogger(SERVICE_NAME)
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")


def detect_listings():
    """Stub — implemented in Session 4."""
    pass


def detect_depegs():
    """Stub — implemented in Session 2."""
    pass


def detect_memecoin_velocity():
    """Stub — implemented in Session 5."""
    pass


def refresh_event_calendar():
    """Stub — implemented in Session 3."""
    pass


def update_price_cache():
    """Stub — implemented in Session 2."""
    pass


def main():
    logger.info(f"{SERVICE_NAME} | starting up")
    last_run = {
        "listings": 0, "depegs": 0, "memecoin": 0, "events": 0, "prices": 0,
    }
    while True:
        now = time.time()
        try:
            if now - last_run["prices"]   >= PRICE_CACHE_INTERVAL:
                update_price_cache();        last_run["prices"]   = now
            if now - last_run["listings"] >= LISTING_POLL_INTERVAL:
                detect_listings();           last_run["listings"] = now
            if now - last_run["depegs"]   >= DEPEG_POLL_INTERVAL:
                detect_depegs();             last_run["depegs"]   = now
            if now - last_run["memecoin"] >= MEMECOIN_POLL_INTERVAL:
                detect_memecoin_velocity();  last_run["memecoin"] = now
            if now - last_run["events"]   >= EVENT_POLL_INTERVAL:
                refresh_event_calendar();    last_run["events"]   = now
        except Exception as e:
            logger.error(f"main loop error: {e}")
        time.sleep(LOOP_SLEEP_SECONDS)


if __name__ == "__main__":
    main()
