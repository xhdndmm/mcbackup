import datetime
import threading
import hashlib
import math
from config import cfg
from log_api import logger
from glob import glob
from tls_adapter import _http
from pathlib import Path
import time

# --- 123pan HTTP API 上传实现 ---
def get_access_token_http():
    """正确使用 123pan 开放平台 API 获取 access_token"""
    conf = cfg["123pan_http"]
    url = f"{conf['api_base_url'].rstrip('/')}/api/v1/access_token"
    body = {
        "clientID": conf["client_id"],
        "clientSecret": conf["client_secret"]
    }
    headers = {
        "Platform": "open_platform",
        "Content-Type": "application/json"
    }
    logger.info("获取 123pan access_token via HTTP (v1 API) -> %s", url)
    r = _http.post(url, headers=headers, json=body, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"token 接口返回 {r.status_code}: {r.text}")
    resp = r.json()
    token = resp.get("data", {}).get("accessToken")
    if not token:
        raise RuntimeError(f"返回中未找到 accessToken: {resp}")
    return token

def list_folder_http(access_token, parent_id, limit=100):
    """列出指定 parent_id 下的文件夹／文件，官方 v2 API"""
    conf = cfg["123pan_http"]
    url = f"{conf['api_base_url'].rstrip('/')}/api/v2/file/list"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Platform": "open_platform",
        "Content-Type": "application/json"
    }
    params = {"parentFileId": parent_id, "limit": limit}
    r = _http.get(url, headers=headers, params=params, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"列出父目录 {parent_id} 失败: {r.status_code}, {r.text}")
    resp = r.json()
    return resp.get("data", {}).get("fileList", [])

def mkdir_http(access_token: str, name: str, parent_id: int) -> int:
    conf = cfg["123pan_http"]
    base = conf["api_base_url"].rstrip("/")
    url = f"{base}/upload/v1/file/mkdir"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Platform": "open_platform",
        "Content-Type": "application/json"
    }
    body = {
        "name": name,
        "parentID": parent_id
    }
    logger.info("创建子目录: 名称=%s, 父目录ID=%s", name, parent_id)
    r = _http.post(url, headers=headers, json=body, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"创建子目录失败: {r.status_code}, {r.text}")
    resp = r.json()
    logger.debug("mkdir 返回内容: %s", resp)
    data = resp.get("data")
    if data is None:
        raise RuntimeError(f"mkdir 接口返回无 data 字段或为空: {resp}")
    # 如果 data 是 dict 并含有 dirID
    if isinstance(data, dict):
        dir_id = data.get("dirID")
        if dir_id is None:
            raise RuntimeError(f"mkdir 接口返回 data 内无 dirID: {resp}")
        try:
            return int(dir_id)
        except ValueError:
            raise RuntimeError(f"mkdir 返回的 dirID 不能解析为 int: {dir_id}")
    # 若接口直接返回 int（少见，但你可能遇到）
    if isinstance(data, int):
        return data
    # 如果到这里，类型不符合预期
    raise RuntimeError(f"mkdir 接口返回 unexpected data type: {resp}")


def get_or_create_date_folder(access_token: str, parent_id: int, date_str: str) -> int:
    """
    在 parent_id 下查找子目录名为 date_str 的目录；如果找到返回其 ID；
    否则创建一个新的目录并返回其 ID。
    """
    # 先列出父目录
    try:
        folder_list = list_folder_http(access_token, parent_id, limit=100)
    except Exception as e:
        logger.warning("列出父目录 %s 失败: %s", parent_id, e)
        folder_list = None

    if folder_list:
        logger.debug("父目录 %s 的子目录列表: %s", parent_id, folder_list)
        for f in folder_list:
            if not isinstance(f, dict):
                logger.warning("跳过 list_folder 返回的非 dict 项: %r", f)
                continue
            name = f.get("filename") or f.get("name")
            ftype = f.get("type")
            try:
                ftype = int(ftype)
            except Exception:
                ftype = None
            # 如果是目录 (假设 type==1 表示文件夹)
            if name == date_str and ftype == 1:
                found_id = f.get("id") or f.get("fileId") or f.get("fid")
                if found_id is not None:
                    try:
                        return int(found_id)
                    except Exception:
                        logger.warning("找到子目录但其 ID 不能转换为 int: %s", found_id)
    # 如果没找到，则创建
    try:
        new_folder_id = mkdir_http(access_token, date_str, parent_id)
        logger.info("创建返回: 目录 ID=%s", new_folder_id)
        return new_folder_id
    except Exception as e:
        logger.error("创建子目录失败: %s", e)
        raise

def compute_etag_md5(filepath: Path) -> str:
    """计算文件的 MD5 值作为 etag（如果接口支持这种方式）"""
    h = hashlib.md5()
    with filepath.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def upload_file_http(access_token: str, parent_id: int, filepath: str):
    """
    创建上传任务并上传文件（支持秒传与分片上传）
    改进版：兼容 data 为 None 的情况，不每次重试都重建任务。
    """
    conf = cfg["123pan_http"]
    base = conf['api_base_url'].rstrip('/')
    file_path = Path(filepath)
    size = file_path.stat().st_size
    etag = compute_etag_md5(file_path)

    # 1. 建立任务
    create_url = f"{base}/upload/v2/file/create"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Platform": "open_platform",
        "Content-Type": "application/json"
    }
    body = {
        "parentFileID": parent_id,
        "filename": file_path.name,
        "size": size,
        "etag": etag
    }
    logger.info("上传任务创建: %s (文件=%s, 大小=%d)", create_url, filepath, size)
    r1 = _http.post(create_url, headers=headers, json=body, timeout=30)
    if r1.status_code != 200:
        raise RuntimeError(f"上传任务创建失败: {r1.status_code}, {r1.text}")
    resp1 = r1.json()
    logger.debug("upload create 返回: %s", resp1)

    data1 = resp1.get("data") or {}
    reuse = data1.get("reuse", False)
    if reuse:
        file_id = data1.get("fileID")
        logger.info("文件 %s 秒传成功，fileID=%s", filepath, file_id)
        return resp1

    preuploadID = data1.get("preuploadID")
    sliceSize = data1.get("sliceSize")
    servers = data1.get("servers") or []
    if not preuploadID or not servers or sliceSize is None:
        raise RuntimeError(f"上传任务创建响应不完整: {resp1}")

    upload_server = servers[0].rstrip('/')
    slice_url = f"{upload_server}/upload/v2/file/slice"
    logger.info("开始分片上传: %s, sliceSize=%s, server=%s", filepath, sliceSize, upload_server)

    total_slices = math.ceil(size / sliceSize)
    logger.info("预计分片数: %d", total_slices)

    # 2. 分片上传循环
    with file_path.open("rb") as f:
        for idx in range(total_slices):
            slice_no = idx + 1
            chunk = f.read(sliceSize)
            md5 = hashlib.md5(chunk).hexdigest()
            files = {"slice": (file_path.name, chunk)}
            data = {
                "preuploadID": preuploadID,
                "sliceNo": str(slice_no),
                "sliceMD5": md5
            }

            logger.debug("上传分片 %d/%d md5=%s", slice_no, total_slices, md5)
            r2 = _http.post(slice_url, headers={
                "Authorization": f"Bearer {access_token}",
                "Platform": "open_platform"
            }, data=data, files=files, timeout=3600)
            if r2.status_code not in (200, 201):
                raise RuntimeError(f"分片上传失败: sliceNo={slice_no}, {r2.status_code}, {r2.text}")
            try:
                resp2 = r2.json()
            except ValueError:
                logger.error("分片上传返回不能解析为 JSON: %s", r2.text)
                raise RuntimeError("分片上传返回非 JSON")

            logger.debug("slice 返回: %s", resp2)
            # 兼容 data 为 None 的情况
            data2 = resp2.get("data")
            if isinstance(data2, dict) and data2.get("completed"):
                logger.info("服务器指示已完成全部切片上传，提前结束分片循环")
                break
            # 否则，继续上传下一片

    # 3. 上传完成通知
    complete_url = f"{base}/upload/v2/file/upload_complete"
    body2 = {"preuploadID": preuploadID}
    logger.info("通知上传完成: %s", complete_url)
    r3 = _http.post(complete_url, headers=headers, json=body2, timeout=30)
    if r3.status_code != 200:
        raise RuntimeError(f"上传完成通知失败: {r3.status_code}, {r3.text}")
    resp3 = r3.json()
    logger.debug("upload finish 返回: %s", resp3)
    if resp3.get("code") != 0 or resp3.get("data") is None:
        raise RuntimeError(f"上传完成通知响应异常: {resp3}")
    file_id = resp3["data"].get("fileID")
    logger.info("文件上传完毕，fileID=%s", file_id)
    return resp3

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

        if used_parent is None:
            logger.error("无法列出任何父目录，上传取消")
            return

        # 使用封装好的函数来获取或创建日期子目录（它会返回 int ID 或 raise）
        try:
            date_folder_id = get_or_create_date_folder(token, used_parent, today_str)
            date_folder_id = int(date_folder_id)
        except Exception as e:
            logger.error("获取/创建日期目录失败: %s", e)
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