# main.py
# https://github.com/xhdndmm/mcbackup
# v1.5
import sys, time, json, logging, subprocess, threading, datetime, requests, pytz, ssl
from pathlib import Path
from logging.handlers import RotatingFileHandler
from pan123.auth import get_access_token
from pan123 import Pan123
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from glob import glob

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

# 日志
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

# TLS 强化 Session
class TLS12Adapter(HTTPAdapter):
    def __init__(self, *args, **kwargs):
        self.ssl_context = ssl.create_default_context()
        try:
            self.ssl_context.set_ciphers("DEFAULT:@SECLEVEL=1")
        except Exception:
            pass
        try:
            self.ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
        except Exception:
            pass
        super().__init__(*args, **kwargs)
    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = self.ssl_context
        return super().init_poolmanager(*args, **kwargs)

def make_robust_session(total_retries=5, backoff_factor=1.0):
    session = requests.Session()
    retry = Retry(
        total=total_retries,
        read=total_retries,
        connect=total_retries,
        backoff_factor=backoff_factor,
        status_forcelist=[500,502,503,504],
        allowed_methods=frozenset(['GET','POST','PUT','DELETE','HEAD','OPTIONS']),
        raise_on_status=False,
        respect_retry_after_header=True
    )
    adapter = TLS12Adapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", HTTPAdapter(max_retries=retry))
    session.headers.update({"User-Agent": "mc_backup/1.0"})
    # 注入 pan123 内部使用的 session
    requests.sessions.Session = lambda: session
    return session

_global_requests_session = make_robust_session()

# MCSManager API
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
    return mcs_request("/api/protected_instance/command", method="GET", params=params)

# 压缩
def make_filename(prefix="mc_backup"):
    return f"{prefix}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.7z"

def compress_full():
    out = Path(cfg["server"]["backup_dir"])
    out.mkdir(parents=True, exist_ok=True)
    fname = make_filename("mc_full_backup")
    dest = out / fname
    cmd = [cfg["server"]["compress_cmd"]] + cfg["server"]["compress_args"] + ["-v9g", str(dest), cfg["server"]["server_dir"]]
    logger.info("执行冷备份压缩: %s", " ".join(cmd))
    subprocess.check_call(cmd)
    logger.info("压缩完成: %s", dest)
    return str(dest)

def compress_worlds():
    out = Path(cfg["server"]["backup_dir"])
    out.mkdir(parents=True, exist_ok=True)
    fname = make_filename("mc_world_backup")
    dest = out / fname
    server_dir = Path(cfg["server"]["server_dir"])
    world_folders = cfg["server"].get("world_folders", ["world"])
    inputs = [str(server_dir / w) for w in world_folders if (server_dir / w).exists()]
    if not inputs:
        raise FileNotFoundError("未找到世界文件夹，请检查 config.json 中的设置")
    cmd = [cfg["server"]["compress_cmd"]] + cfg["server"]["compress_args"] + ["-v9g", str(dest)] + inputs
    logger.info("执行热备份压缩: %s", " ".join(cmd))
    subprocess.check_call(cmd)
    logger.info("世界文件夹压缩完成: %s", dest)
    return str(dest)

# 上传线程（在 parent_folder_id 下创建日期子文件夹上传）
def async_upload(filepath):
    part_files = sorted(glob(filepath + "*"))

    def task():
        max_attempts = 5
        pan = None
        date_folder_id = None
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")

        # 第一步：初始化 pan、获取或创建日期子文件夹
        for attempt in range(1, max_attempts + 1):
            try:
                logger.info("获取 123pan access_token … (尝试 %d/%d)", attempt, max_attempts)
                token = get_access_token(cfg["123pan"]["client_id"], cfg["123pan"]["client_secret"])
                pan = Pan123(token)
                parent_id = cfg["123pan"].get("parent_folder_id", 0)

                # 列出 parent 目录下的子文件／文件夹
                folders = pan.file.list(parent_id, 1000, 1)

                # 查找是否已有 name == today_str 的子目录
                folder = next((f for f in folders if f.get("name") == today_str and f.get("is_dir", False)), None)
                if folder:
                    date_folder_id = folder["id"]
                else:
                    logger.info("在父目录 %s 下创建日期子目录: %s", parent_id, today_str)
                    res = pan.file.mkdir(parent_id, today_str)
                    # 依据 SDK 返回格式取 id
                    date_folder_id = res.get("data", {}).get("id") or res.get("id")

                logger.info("上传目标为目录 %s (ID=%s)", today_str, date_folder_id)
                if date_folder_id is None:
                    raise RuntimeError("未能获得日期目录的 ID")
                break
            except Exception as e:
                logger.exception("获取/创建日期目录失败: %s", e)
                if attempt < max_attempts:
                    wait = min(30, 2**attempt)
                    logger.info("等待 %d 秒后重试 …", wait)
                    time.sleep(wait)
                else:
                    logger.error("多次失败，取消上传")
                    return

        # 第二步：上传各个分卷到这个日期目录
        for f in part_files:
            for attempt in range(1, max_attempts + 1):
                try:
                    logger.info("上传 %s 到 123pan %s (尝试 %d/%d)", f, today_str, attempt, max_attempts)
                    res = pan.file.upload(date_folder_id, f)
                    logger.info("上传成功: %s", res)

                    if cfg.get("backup", {}).get("storage", "both") == "cloud":
                        try:
                            Path(f).unlink()
                            logger.info("删除本地备份，仅保留云端: %s", f)
                        except Exception as e:
                            logger.warning("本地删除失败: %s", e)
                    break
                except Exception as e:
                    logger.exception("上传失败: %s", e)
                    if attempt < max_attempts:
                        sleep_for = min(60, 2**attempt)
                        logger.info("等待 %d 秒后重试 …", sleep_for)
                        time.sleep(sleep_for)
                    else:
                        logger.error("上传分卷超限失败: %s", f)
                        return

        logger.info("所有分卷上传完成")

    t = threading.Thread(target=task, daemon=False)
    t.start()
    return t

# 主流程
def do_backup():
    mode = cfg.get("backup", {}).get("mode", "cold")
    try:
        logger.info("=== 开始备份（模式 %s） ===", mode)
        if mode == "cold":
            mcs_stop()
            time.sleep(8)
            backup_file = compress_full()
            mcs_start()
        elif mode == "hot":
            mcs_command("save-off")
            mcs_command("save-all")
            time.sleep(3)
            backup_file = compress_worlds()
            mcs_command("save-on")
        else:
            raise ValueError(f"未知备份模式: {mode}")
        async_upload(backup_file)
        logger.info("备份任务触发，上传在后台执行")
    except Exception as e:
        logger.exception("备份流程失败: %s", e)
        if mode == "cold":
            try:
                mcs_start()
            except Exception:
                logger.error("重启服务器失败，请人工检查")

# 定时任务注册
def register_jobs():
    tz = pytz.timezone(cfg["schedule"]["timezone"])
    sched = BlockingScheduler(timezone=tz)
    for t in cfg["schedule"]["times"]:
        hh, mm = t.split(":")
        trigger = CronTrigger(hour=int(hh), minute=int(mm), timezone=tz)
        sched.add_job(do_backup, trigger)
        logger.info("已注册每日 %s:%s 备份任务（时区 %s）", hh, mm, cfg["schedule"]["timezone"])
    return sched

if __name__ == "__main__":
    sched = register_jobs()
    logger.info("定时器启动")
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("调度停止")

# 调试时使用
# if __name__ == "__main__":
#     do_backup()
