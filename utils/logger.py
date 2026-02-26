"""
Centralised logging setup.
Each module calls setup_logger(__name__) to get its named logger.
"""
import logging
import os
from datetime import datetime
from config.settings import LOG_DIR


def setup_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """
    Return a logger that writes to both stdout and a daily rotating log file.
    Safe to call multiple times — handlers are only added once.
    """
    os.makedirs(LOG_DIR, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(level)

    if logger.handlers:
        return logger  # Already configured

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)-28s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logger.addHandler(console)

    # Daily file
    today = datetime.now().strftime("%Y-%m-%d")
    fh = logging.FileHandler(os.path.join(LOG_DIR, f"trading_{today}.log"))
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger
