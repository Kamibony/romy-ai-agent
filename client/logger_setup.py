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

    # Remove any existing handlers
    if logger.hasHandlers():
        logger.handlers.clear()

    # File handler
    fh = logging.FileHandler(log_file, encoding='utf-8')
    fh.setLevel(logging.INFO)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    # Console handler
    import codecs
    # Make sure stdout uses utf-8 encoding safely without breaking other stdout uses
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding='utf-8')
            stream = sys.stdout
        except Exception:
            stream = codecs.getwriter('utf-8')(sys.stdout.buffer, 'replace')
    else:
        stream = codecs.getwriter('utf-8')(sys.stdout.buffer, 'replace')

    ch = logging.StreamHandler(stream)
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

setup_logger()