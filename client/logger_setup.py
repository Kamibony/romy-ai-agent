import logging
import os
import sys

def setup_logger():
    user_data_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "RomyAgentBrowserData")
    os.makedirs(user_data_dir, exist_ok=True)
    log_file = os.path.join(user_data_dir, "romy_agent.log")

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # File handler
    fh = logging.FileHandler(log_file)
    fh.setLevel(logging.INFO)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

setup_logger()
