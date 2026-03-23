import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import requests
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from zoneinfo import ZoneInfo

BASE_URL = "https://api.quantphemes.com"
HK_TZ = ZoneInfo("Asia/Hong_Kong")
UTC_TZ = timezone.utc
WEIGHT_CHOICES = np.array([0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0])

LOGGER_NAME = "module1_random_sender"
_FILE_HANDLER: Optional[logging.FileHandler] = None
_FILE_HANDLER_DATE: Optional[str] = None
_FILE_HANDLER_LOCK = threading.Lock()

FIRST_POST_SENT_TODAY = False
STATE_LOCK = threading.Lock()


def setup_logger() -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = False

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    ensure_daily_file_handler(logger)
    return logger


def ensure_daily_file_handler(logger: logging.Logger) -> None:
    global _FILE_HANDLER, _FILE_HANDLER_DATE

    today_hkt = datetime.now(HK_TZ).strftime("%Y%m%d")
    if _FILE_HANDLER_DATE == today_hkt and _FILE_HANDLER is not None:
        return

    with _FILE_HANDLER_LOCK:
        today_hkt = datetime.now(HK_TZ).strftime("%Y%m%d")
        if _FILE_HANDLER_DATE == today_hkt and _FILE_HANDLER is not None:
            return

        logs_dir = Path("logs")
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_path = logs_dir / f"sender_{today_hkt}.log"

        if _FILE_HANDLER is not None:
            logger.removeHandler(_FILE_HANDLER)
            _FILE_HANDLER.close()

        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        _FILE_HANDLER = logging.FileHandler(log_path, encoding="utf-8")
        _FILE_HANDLER.setLevel(logging.INFO)
        _FILE_HANDLER.setFormatter(formatter)
        logger.addHandler(_FILE_HANDLER)
        _FILE_HANDLER_DATE = today_hkt


def load_config() -> dict:
    load_dotenv()

    api_key = os.getenv("API_KEY")
    strategy_id = os.getenv("STRATEGY_ID")

    missing = [name for name, value in {"API_KEY": api_key, "STRATEGY_ID": strategy_id}.items() if not value]
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

    return {
        "api_key": api_key,
        "strategy_id": strategy_id,
        "base_url": BASE_URL,
    }


def reset_daily_post_flag() -> None:
    global FIRST_POST_SENT_TODAY
    with STATE_LOCK:
        FIRST_POST_SENT_TODAY = False

    logger = logging.getLogger(LOGGER_NAME)
    ensure_daily_file_handler(logger)
    logger.info("Daily state reset at midnight HKT. Next in-day call will use POST.")


def choose_weight() -> float:
    return float(np.random.choice(WEIGHT_CHOICES))


def build_payload(weight: float, is_post: bool) -> dict:
    holding_item = {
        "effective_datetime": datetime.now(UTC_TZ).isoformat(),
        "stocks": [
            {
                "symbol": "2800.HK",
                "percentage": weight,
            }
        ],
    }

    if is_post:
        return {
            "name": "Random HKEX Single-Asset Weights",
            "description": "Randomly generated holdings for 2800.HK during HKEX session windows.",
            "holdings": [holding_item],
        }

    return {
        "holdings": [holding_item],
    }


def send_once(config: dict, logger: logging.Logger) -> None:
    global FIRST_POST_SENT_TODAY

    ensure_daily_file_handler(logger)
    weight = choose_weight()

    with STATE_LOCK:
        request_type = "POST" if not FIRST_POST_SENT_TODAY else "PATCH"

    url = f"{config['base_url']}/api/v1/strategy/{config['strategy_id']}/holding"
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
    }
    payload = build_payload(weight, is_post=(request_type == "POST"))

    for attempt in (1, 2):
        try:
            response = requests.request(
                method=request_type,
                url=url,
                headers=headers,
                json=payload,
                timeout=20,
            )

            status_code = response.status_code
            response_body = response.text.strip()
            timestamp_hkt = datetime.now(HK_TZ).isoformat()

            logger.info(
                "API_CALL | timestamp_hkt=%s | weight=%.1f | request_type=%s | status_code=%s | response_body=%s",
                timestamp_hkt,
                weight,
                request_type,
                status_code,
                response_body,
            )

            response.raise_for_status()

            if request_type == "POST":
                with STATE_LOCK:
                    FIRST_POST_SENT_TODAY = True
            return
        except requests.RequestException as exc:
            logger.error(
                "API_ERROR | attempt=%s | request_type=%s | weight=%.1f | error=%s",
                attempt,
                request_type,
                weight,
                str(exc),
            )
            if attempt == 1:
                logger.warning("Retrying once in 30 seconds...")
                time.sleep(30)
            else:
                logger.error("Retry failed. Skipping this decision point.")


def run_scheduled_send(config: dict, logger: logging.Logger) -> None:
    try:
        send_once(config, logger)
    except Exception as exc:
        ensure_daily_file_handler(logger)
        logger.exception("Unexpected job error, skipped without crashing scheduler: %s", str(exc))


def build_scheduler(config: dict, logger: logging.Logger) -> BlockingScheduler:
    scheduler = BlockingScheduler(timezone=HK_TZ)

    job_kwargs = {
        "func": run_scheduled_send,
        "args": [config, logger],
        "misfire_grace_time": 60,
        "coalesce": True,
        "max_instances": 1,
    }

    scheduler.add_job(
        trigger=CronTrigger(day_of_week="mon-fri", hour=9, minute="35-55/5", timezone=HK_TZ),
        id="send_hkex_opening_window",
        **job_kwargs,
    )
    scheduler.add_job(
        trigger=CronTrigger(day_of_week="mon-fri", hour="10-15", minute="*/5", timezone=HK_TZ),
        id="send_hkex_main_window",
        **job_kwargs,
    )

    scheduler.add_job(
        func=reset_daily_post_flag,
        trigger=CronTrigger(hour=0, minute=0, timezone=HK_TZ),
        id="daily_reset_post_flag",
        replace_existing=True,
    )

    return scheduler


def get_next_run_time_hkt(scheduler: BlockingScheduler) -> Optional[str]:
    jobs = scheduler.get_jobs()
    now_hkt = datetime.now(HK_TZ)
    next_run_times = []
    for job in jobs:
        if not job.id.startswith("send_"):
            continue
        next_fire = job.trigger.get_next_fire_time(previous_fire_time=None, now=now_hkt)
        if next_fire is not None:
            next_run_times.append(next_fire)

    if not next_run_times:
        return None

    next_run = min(next_run_times).astimezone(HK_TZ)
    return next_run.isoformat()


def main() -> None:
    logger = setup_logger()
    ensure_daily_file_handler(logger)

    config = load_config()
    scheduler = build_scheduler(config, logger)

    next_run_hkt = get_next_run_time_hkt(scheduler)

    startup_message = (
        f"Random sender started | timezone=Asia/Hong_Kong | strategy_id={config['strategy_id']} "
        f"| next_scheduled_fire={next_run_hkt}"
    )
    print(startup_message)
    logger.info(startup_message)

    scheduler.start()


if __name__ == "__main__":
    main()