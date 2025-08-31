import sys, time, json, logging, subprocess, threading, datetime, requests, pytz
from pathlib import Path
from logging.handlers import RotatingFileHandler
from pan123.auth import get_access_token
from pan123 import Pan123
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

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
        "compress_args": ["a", "-mx=9","-mmt=on"],
        "world_folders": ["world", "world_nether", "world_the_end"]
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
    },
    "backup": {
        "mode": "cold"   # 可选: cold / hot
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
handler = RotatingFileHandler(
    log_cfg["log_file"],
    maxBytes=log_cfg["max_bytes"],
    backupCount=log_cfg["backup_count"],
    encoding="utf-8"
)
handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger.addHandler(handler)
logger.info("脚本启动")

# MCSManager API 调用
MCS_BASE = cfg["mcsmanager"]["base_url"].rstrip("/")
MCS_APIKEY = cfg["mcsmanager"]["apikey"]
DAEMON_ID = cfg["mcsmanager"].get("daemonId")
INSTANCE_UUID = cfg["mcsmanager"]["instance_uuid"]
HEADERS = {"X-Requested-With": "XMLHttpRequest", "Content-Type": "application/json; charset=utf-8"}

def mcs_request(path, method="GET", params=None, json_body=None):
    url = f"{MCS_BASE}{path}"
    params = params or {}
    params["apikey"] = MCS_APIKEY
    r = requests.request(method, url, params=params, json=json_body, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()

def mcs_stop():
    logger.info("停止 MC 服务器")
    params = {"uuid": INSTANCE_UUID}
    if DAEMON_ID:
        params["daemonId"] = DAEMON_ID
    return mcs_request("/api/protected_instance/stop", params=params)

def mcs_start():
    logger.info("启动 MC 服务器")
    params = {"uuid": INSTANCE_UUID}
    if DAEMON_ID:
        params["daemonId"] = DAEMON_ID
    return mcs_request("/api/protected_instance/open", params=params)

def mcs_command(cmd):
    logger.info("发送命令到 MC 控制台: %s", cmd)
    params = {"uuid": INSTANCE_UUID, "command": cmd}
    if DAEMON_ID:
        params["daemonId"] = DAEMON_ID
    # 使用 GET 请求发送命令
    return mcs_request("/api/protected_instance/command", method="GET", params=params)

# 压缩过程
def make_filename(prefix="mc_backup"):
    return f"{prefix}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.7z"

def compress_full():
    """压缩整个服务器目录（冷备份用）"""
    out = Path(cfg["server"]["backup_dir"])
    out.mkdir(parents=True, exist_ok=True)
    fname = make_filename("mc_full_backup")
    dest = out / fname
    cmd = [cfg["server"]["compress_cmd"]] + cfg["server"]["compress_args"] + [str(dest), cfg["server"]["server_dir"]]
    logger.info("执行冷备份压缩命令: %s", " ".join(cmd))
    subprocess.check_call(cmd)
    logger.info("压缩完成: %s", dest)
    return str(dest)

def compress_worlds():
    """只压缩 world 系列文件夹（热备份用）"""
    out = Path(cfg["server"]["backup_dir"])
    out.mkdir(parents=True, exist_ok=True)
    fname = make_filename("mc_world_backup")
    dest = out / fname

    server_dir = Path(cfg["server"]["server_dir"])
    world_folders = cfg["server"].get("world_folders", ["world"])
    inputs = [str(server_dir / w) for w in world_folders if (server_dir / w).exists()]

    if not inputs:
        raise FileNotFoundError("未找到任何世界文件夹，请检查 config.json 中的 server.world_folders 设置")

    cmd = [cfg["server"]["compress_cmd"]] + cfg["server"]["compress_args"] + [str(dest)] + inputs
    logger.info("执行热备份压缩命令: %s", " ".join(cmd))
    subprocess.check_call(cmd)
    logger.info("世界文件夹压缩完成: %s", dest)
    return str(dest)

# 后台上传线程
def async_upload(filepath):
    def task():
        try:
            logger.info("获取 123pan access_token …")
            token = get_access_token(cfg["123pan"]["client_id"], cfg["123pan"]["client_secret"])
            pan = Pan123(token)
            pid = cfg["123pan"].get("parent_folder_id", 0)
            logger.info("开始上传 %s 到 123pan 目录 %s …", filepath, pid)
            res = pan.file.upload(pid, filepath)
            logger.info("上传成功: %s", res)
        except Exception as e:
            logger.exception("后台上传失败: %s", e)

    t = threading.Thread(target=task, daemon=False)
    t.start()
    return t

# 主流程
def do_backup():
    mode = cfg.get("backup", {}).get("mode", "cold")
    try:
        logger.info("=== 执行备份流程 (模式: %s) ===", mode)
        if mode == "cold":
            mcs_stop()
            time.sleep(8)
            backup_file = compress_full()
            mcs_start()
        elif mode == "hot":
            mcs_command("save-off")
            mcs_command("save-all")
            time.sleep(3)  # 给 MC 保存时间
            backup_file = compress_worlds()
            mcs_command("save-on")
        else:
            raise ValueError(f"未知备份模式: {mode}")

        async_upload(backup_file)
        logger.info("备份完成（上传已在后台）")
    except Exception as e:
        logger.exception("备份流程出错: %s", e)
        if mode == "cold":
            try:
                mcs_start()
            except:
                logger.error("尝试恢复服务器启动失败，请手动检查")

# 定时任务注册
def register_jobs():
    tz = pytz.timezone(cfg["schedule"]["timezone"])
    sched = BlockingScheduler(timezone=tz)

    for t in cfg["schedule"]["times"]:
        hh, mm = t.split(":")
        trigger = CronTrigger(hour=int(hh), minute=int(mm), timezone=tz)
        sched.add_job(do_backup, trigger)
        logger.info("已注册定时任务: 每天 %s:%s (%s)", hh, mm, cfg["schedule"]["timezone"])

    return sched

if __name__ == "__main__":
    sched = register_jobs()
    logger.info("定时调度器启动")
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("调度器已停止")

# 调试时使用
#if __name__ == "__main__":
#     do_backup()
