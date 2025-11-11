# main.py
# v1.6

import sys
import time
import json
import subprocess
import threading
import datetime
import ssl
from pathlib import Path
from glob import glob
import logging
from logging.handlers import RotatingFileHandler
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pytz
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

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
        "compress_args": ["a", "-mx=9", "-mmt=on"],
        "world_folders": ["world", "world_nether", "world_the_end"]
    },
    "123pan_http": {
        # 假设这是 pan123 的 HTTP API 基础 URL，如 “https://open-api.123pan.com”
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

# --- 日志设置 ---
log_cfg = cfg["logging"]
logger = logging.getLogger("mc_backup")
logger.setLevel(logging.INFO)
handler = logging.handlers.RotatingFileHandler(
    log_cfg["log_file"],
    maxBytes=log_cfg["max_bytes"],
    backupCount=log_cfg["backup_count"],
    encoding="utf-8"
)
handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger.addHandler(handler)
logger.info("脚本启动")

# --- TLS 强化 Session ---
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
    session.headers.update({"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"})
    return session

_http = make_robust_session()

# --- MCSManager API 配置 ---
MCS_BASE = cfg["mcsmanager"]["base_url"].rstrip("/")
MCS_APIKEY = cfg["mcsmanager"]["apikey"]
DAEMON_ID = cfg["mcsmanager"].get("daemonId")
INSTANCE_UUID = cfg["mcsmanager"]["instance_uuid"]
HEADERS = {"X-Requested-With": "XMLHttpRequest", "Content-Type": "application/json; charset=utf-8"}

def mcs_request(path, method="GET", params=None, json_body=None):
    url = f"{MCS_BASE}{path}"
    params = params or {}
    params["apikey"] = MCS_APIKEY
    r = _http.request(method, url, params=params, json=json_body, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()

def mcs_stop():
    logger.info("停止 MC 服务器")
    params = {"uuid": INSTANCE_UUID}
    if DAEMON_ID:
        params["daemonId"] = DAEMON_ID
    return mcs_request("/api/protected_instance/stop", method="GET", params=params)

def mcs_start():
    logger.info("启动 MC 服务器")
    params = {"uuid": INSTANCE_UUID}
    if DAEMON_ID:
        params["daemonId"] = DAEMON_ID
    return mcs_request("/api/protected_instance/open", method="GET", params=params)

def mcs_command(cmd):
    logger.info("发送命令到 MC 控制台: %s", cmd)
    params = {"uuid": INSTANCE_UUID, "command": cmd}
    if DAEMON_ID:
        params["daemonId"] = DAEMON_ID
    return mcs_request("/api/protected_instance/command", method="GET", params=params)

# --- 123pan HTTP API 上传实现 ---
def get_access_token_http():
    """通过 HTTP 接口获取 access_token（假设接口为 api_base_url + '/auth/token'）"""
    conf = cfg["123pan_http"]
    url = f"{conf['api_base_url'].rstrip('/')}/auth/token"
    data = {
        "client_id": conf["client_id"],
        "client_secret": conf["client_secret"],
        "grant_type": "client_credentials"
    }
    logger.info("获取 123pan access_token via HTTP")
    r = _http.post(url, json=data, timeout=30)
    r.raise_for_status()
    resp = r.json()
    token = resp.get("access_token") or resp.get("token")
    if not token:
        raise RuntimeError(f"获取 access_token 失败: {resp}")
    return token

def list_folder_http(access_token, parent_id, limit=100):
    """列出指定 parent_id 下的文件夹／文件"""
    conf = cfg["123pan_http"]
    url = f"{conf['api_base_url'].rstrip('/')}/file/list"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"parentID": parent_id, "limit": limit}
    r = _http.get(url, headers=headers, params=params, timeout=30)
    r.raise_for_status()
    return r.json().get("fileList") or []

def mkdir_http(access_token, name, parent_id):
    """在 parent_id 下创建子目录 name"""
    conf = cfg["123pan_http"]
    url = f"{conf['api_base_url'].rstrip('/')}/file/mkdir"
    headers = {"Authorization": f"Bearer {access_token}"}
    body = {"name": name, "parentID": parent_id}
    r = _http.post(url, json=body, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()

def upload_file_http(access_token, parent_id, filepath):
    """上传文件 filepath 到 parent_id 目录"""
    conf = cfg["123pan_http"]
    url = f"{conf['api_base_url'].rstrip('/')}/file/upload"
    headers = {"Authorization": f"Bearer {access_token}"}
    with open(filepath, "rb") as f:
        files = {"file": (Path(filepath).name, f)}
        data = {"parentID": parent_id}
        r = _http.post(url, headers=headers, data=data, files=files, timeout=3600)
    r.raise_for_status()
    return r.json()

def async_upload(filepath):
    part_files = sorted(glob(filepath + "*"))

    def task():
        token = None
        for attempt in range(1, 6):
            try:
                token = get_access_token_http()
                break
            except Exception as e:
                logger.warning("获取 access_token 失败 %d/5: %s", attempt, e)
                time.sleep(min(30, 2**attempt))
        if not token:
            logger.error("无法获取 access_token，上传取消")
            return

        parent_id = cfg["123pan_http"].get("parent_folder_id", 0) or 0
        try_parents = [parent_id]
        if parent_id != 0:
            try_parents.append(0)
        used_parent = None
        folder_list = None
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")

        for pid in try_parents:
            try:
                folder_list = list_folder_http(token, pid, limit=100)
                used_parent = pid
                break
            except Exception as e:
                logger.warning("列出父目录 %s 失败: %s", pid, e)
                continue

        if folder_list is None:
            logger.error("无法列出任何父目录，上传取消")
            return

        # 查找今日目录
        date_folder_id = None
        for f in folder_list:
            if (f.get("filename") == today_str or f.get("name") == today_str) and int(f.get("type", 1)) == 1:
                date_folder_id = f.get("id") or f.get("fileId") or f.get("fid")
                break

        if not date_folder_id:
            try:
                logger.info("在父目录 %s 下创建日期子目录: %s", used_parent, today_str)
                mkdir_resp = mkdir_http(token, today_str, used_parent)
                date_folder_id = mkdir_resp.get("id") or mkdir_resp.get("fileId") or mkdir_resp.get("fid")
                logger.info("创建返回: %s -> 目录 ID=%s", mkdir_resp, date_folder_id)
            except Exception as e:
                logger.error("创建子目录失败: %s", e)
                return

        # 上传各个分卷
        for f in part_files:
            uploaded = False
            for attempt in range(1, 6):
                try:
                    logger.info("上传 %s 到 123pan (目录ID=%s) 尝试 %d/5", f, date_folder_id, attempt)
                    upload_resp = upload_file_http(token, date_folder_id, f)
                    logger.info("上传成功: %s", upload_resp)
                    uploaded = True
                    if cfg.get("backup", {}).get("storage", "both") == "cloud":
                        try:
                            Path(f).unlink()
                            logger.info("删除本地备份，仅保留云端: %s", f)
                        except Exception as e:
                            logger.warning("本地删除失败: %s", e)
                    break
                except Exception as e:
                    logger.warning("上传 %s 失败 %d/5: %s", f, attempt, e)
                    time.sleep(min(60, 2**attempt))
                    continue
            if not uploaded:
                logger.error("文件 %s 上传失败，已跳过后续重试", f)

        logger.info("所有分卷上传流程结束 (部分文件可能上传失败)")

    t = threading.Thread(target=task, daemon=False)
    t.start()
    return t

# --- 压缩模块 ---
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

# --- 主流程 ---
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

# --- 定时任务注册 ---
def register_jobs():
    tz = pytz.timezone(cfg["schedule"]["timezone"])
    sched = BlockingScheduler(timezone=tz)
    for t in cfg["schedule"]["times"]:
        hh, mm = t.split(":")
        trigger = CronTrigger(hour=int(hh), minute=int(mm), timezone=tz)
        sched.add_job(do_backup, trigger)
        logger.info("已注册每日 %s:%s 备份任务（时区 %s）", hh, mm, cfg["schedule"]["timezone"])
    return sched

#if __name__ == "__main__":
#    sched = register_jobs()
#    logger.info("定时器启动")
#    try:
#        sched.start()
#    except (KeyboardInterrupt, SystemExit):
#        logger.info("调度停止")

#debug
do_backup()