from config import cfg
import logging
from logging.handlers import RotatingFileHandler

# --- 日志设置 ---
log_cfg = cfg["logging"]
logger = logging.getLogger("mc_backup")
handler = RotatingFileHandler(
    log_cfg["log_file"],
    maxBytes=log_cfg["max_bytes"],
    backupCount=log_cfg["backup_count"],
    encoding="utf-8"
)
handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))