import json
from pathlib import Path
import sys

# --- 配置部分 ---
CONFIG_PATH = Path(__file__).parent / "config.json"
DEFAULT_CONFIG = {
    "mcsmanager": {
        "base_url": "http://panel.example.com",
        "apikey": "YOUR_MCSM_APIKEY",
        "daemonId": "",
        "instance_uuid": ""
    },
    "server": {
        "server_dir": "/home/mc/server",
        "backup_dir": "/home/mc/backups",
        "compress_cmd": "7z",
        "compress_args": ["a", "-mx=6", "-mmt=on"],
        "world_folders": ["world", "world_nether", "world_the_end"]
    },
    "123pan_http": {
        "api_base_url": "https://open-api.123pan.com",
        "client_id": "YOUR_CLIENT_ID",
        "client_secret": "YOUR_CLIENT_SECRET",
        "parent_folder_id": 0
    },
    "schedule": {
        "times": ["03:00"],
        "timezone": "Asia/Shanghai"
    },
    "logging": {
        "log_file": "mc_backup.log",
        "max_bytes": 10_000_000,
        "backup_count": 5
    },
    "backup": {
        "mode": "cold",
        "keep_days": 7,
        "keep_count": 10,
        "storage": "both"
    }
}

def ensure_config():
    if not CONFIG_PATH.exists():
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2, ensure_ascii=False)
        print(f"[INFO] 已生成默认配置文件 {CONFIG_PATH}，请填写后重试。")
        sys.exit(0)

ensure_config()

cfg = json.load(open(CONFIG_PATH, "r", encoding="utf-8"))