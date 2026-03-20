from log_api import logger
from config import cfg
from tls_adapter import _http

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