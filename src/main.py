import sys, time, json, logging, subprocess, threading, datetime, requests, schedule
from pathlib import Path
from logging.handlers import RotatingFileHandler
from pan123.auth import get_access_token
from pan123 import Pan123

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
        "compress_args": ["a", "-mx=9"]
    },
    "123pan": {
        "client_id": "YOUR_123PAN_CLIENT_ID",
        "client_secret": "YOUR_123PAN_CLIENT_SECRET",
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

# 日志初始化
log_cfg = cfg["logging"]
logger = logging.getLogger("mc_backup")
logger.setLevel(logging.INFO)
handler = RotatingFileHandler(log_cfg["log_file"], maxBytes=log_cfg["max_bytes"], backupCount=log_cfg["backup_count"], encoding="utf-8")
handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger.addHandler(handler)
logger.info("脚本启动")

# MCSManager API 调用
MCS_BASE = cfg["mcsmanager"]["base_url"].rstrip("/")
MCS_APIKEY = cfg["mcsmanager"]["apikey"]
DAEMON_ID = cfg["mcsmanager"].get("daemonId")
INSTANCE_UUID = cfg["mcsmanager"]["instance_uuid"]
HEADERS = {"X-Requested-With":"XMLHttpRequest", "Content-Type":"application/json; charset=utf-8"}

def mcs_request(path, method="GET", params=None, json_body=None):
    url = f"{MCS_BASE}{path}"
    params = params or {}
    params["apikey"] = MCS_APIKEY
    r = requests.request(method, url, params=params, json=json_body, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()

def mcs_stop():
    logger.info("停止 MC 服务器")
    params={"uuid":INSTANCE_UUID}
    if DAEMON_ID: params["daemonId"]=DAEMON_ID
    return mcs_request("/api/protected_instance/stop", params=params)

def mcs_start():
    logger.info("启动 MC 服务器")
    params={"uuid":INSTANCE_UUID}
    if DAEMON_ID: params["daemonId"]=DAEMON_ID
    return mcs_request("/api/protected_instance/open", params=params)

# 压缩过程
def make_filename():
    return f"mc_backup_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.7z"

def compress():
    out = Path(cfg["server"]["backup_dir"])
    out.mkdir(parents=True, exist_ok=True)
    fname = make_filename()
    dest = out / fname
    cmd = [cfg["server"]["compress_cmd"]] + cfg["server"]["compress_args"] + [str(dest), cfg["server"]["server_dir"]]
    logger.info("执行压缩命令: %s", " ".join(cmd))
    subprocess.check_call(cmd)
    logger.info("压缩完成: %s", dest)
    return str(dest)

# 后台上传线程
def async_upload(filepath):
    def task():
        try:
            pan = None
            logger.info("获取 123pan access_token …")
            token = get_access_token(cfg["123pan"]["client_id"], cfg["123pan"]["client_secret"])
            pan = Pan123(token)
            pid = cfg["123pan"].get("parent_folder_id", 0)
            logger.info("开始上传 %s 到 123pan 目录 %s …", filepath, pid)
            res = pan.file.upload(pid, filepath)
            logger.info("上传成功: %s", res)
        except Exception as e:
            logger.exception("后台上传失败: %s", e)
    t = threading.Thread(target=task, daemon=True)
    t.start()

# 主流程
def do_backup():
    try:
        logger.info("=== 执行备份流程 ===")
        mcs_stop()
        time.sleep(8)
        backup_file = compress()
        mcs_start()
        async_upload(backup_file)
        logger.info("备份完成（上传已在后台）")
    except Exception as e:
        logger.exception("备份流程出错: %s", e)
        try:
            mcs_start()
        except:
            logger.error("尝试恢复服务器启动失败，请手动检查")

# 定时任务注册
for t in cfg["schedule"]["times"]:
    schedule.every().day.at(t).do(do_backup)
logger.info("已注册定时: %s", cfg["schedule"]["times"])

if __name__ == "__main__":
    while True:
        schedule.run_pending()
        time.sleep(10)

#调试时使用
#if __name__ == "__main__":
#    do_backup()