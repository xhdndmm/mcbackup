import subprocess
import datetime

# --- 压缩模块 ---
def make_filename(prefix="mc_backup"):
    return f"{prefix}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.7z"

def compress_full():
    out = Path(cfg["server"]["backup_dir"])
    out.mkdir(parents=True, exist_ok=True)
    fname = make_filename("mc_full_backup")
    dest = out / fname
    cmd = [cfg["server"]["compress_cmd"]] + cfg["server"]["compress_args"] + ["-v8g", str(dest), cfg["server"]["server_dir"]]
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
    cmd = [cfg["server"]["compress_cmd"]] + cfg["server"]["compress_args"] + ["-v8g", str(dest)] + inputs
    logger.info("执行热备份压缩: %s", " ".join(cmd))
    subprocess.check_call(cmd)
    logger.info("世界文件夹压缩完成: %s", dest)
    return str(dest)