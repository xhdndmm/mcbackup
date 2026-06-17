import sys
import time
import logging
import pytz
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from log_api import *
from config import *
from mcsm_api import *
from pan_api import *
from compress_api import *

logger.addHandler(handler)
logger.info("脚本启动")

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

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "run_once":
        # 调试
        logger.setLevel(logging.DEBUG)
        do_backup()
    else:
        # 正常运行
        logger.setLevel(logging.INFO)
        sched = register_jobs()
        logger.info("mcbackup version",VERSION)
        logger.info("定时器启动")
        try:
            sched.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("调度停止")
