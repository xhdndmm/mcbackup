# 欢迎浏览本项目！
## 这是什么？
一个基于 **Python + MCSManager API + 123 云盘 API** 的Minecraft服务器自动化备份工具。  

功能特点：
- 自动生成 `config.json` 配置文件（首次运行时）
- 支持两种备份模式：
  - **冷备份 (cold)**：停服 → 压缩 → 启动
  - **热备份 (hot)**：save-off → save-all → 压缩世界文件夹 → save-on（无需停服）
- 使用 `7z` 压缩服务器目录
- 压缩完成后立即恢复正常运行，**上传任务在后台线程执行**
- 上传至 **123 云盘**（使用官方开放平台 API / `pan123` SDK）
- 支持多时段 **定时任务**
- 支持 **日志文件轮转**，便于长期运行

---

## 环境要求

- 操作系统：Linux
- Python（版本：`>=3.8`）
- [MCSManager 面板](https://mcsmanager.com/)
- 系统依赖：
```bash
sudo apt update && sudo apt install p7zip-full
```

- Python 依赖：
```bash
pip install -r requirements.txt
```

---

## 配置文件说明 (`config.json`)

脚本第一次运行会自动生成示例配置文件并退出，你需要手动修改其中的内容。

```json
{
  "mcsmanager": {
    "base_url": "http://panel.example.com",   // MCSManager 面板地址
    "apikey": "YOUR_MCSM_APIKEY",             // 面板 API Key
    "daemonId": "your-daemon-id",             // 实例ID
    "instance_uuid": "your-instance-uuid"     // 节点ID
  },
  "server": {
    "server_dir": "/home/mc/server",          // Minecraft 服务器目录
    "backup_dir": "/home/mc/backups",         // 本地备份目录
    "compress_cmd": "7z",                     // 压缩命令
    "compress_args": ["a", "-mx=9"]           // 压缩参数
  },
  "123pan": {
    "client_id": "YOUR_123PAN_CLIENT_ID",     // 123 云盘API Client ID
    "client_secret": "YOUR_123PAN_CLIENT_SECRET", // 123 云盘API Client Secret
    "parent_folder_id": 0                     // 云盘目录 ID（0 为根目录）
  },
  "schedule": {
    "times": ["03:00", "15:00"],              // 每天备份时间（24小时制，支持多个）
    "timezone": "Asia/Shanghai"               // 时区
  },
  "logging": {
    "log_file": "mc_backup.log",              // 日志文件路径
    "max_bytes": 10485760,                    // 单个日志文件大小 (10MB)
    "backup_count": 5                         // 日志轮转数量
  },
  "backup": {
    "mode": "cold",                          // 可选: cold / hot
    "keep_days": 7,                          // 保留多少天
    "keep_count": 10,                        // 至少保留多少个最新备份
    "storage": "both"                        // 可选: both（云端+本地） / cloud（云端）
  }
}
```

---

## 使用方法

1. **第一次运行**

   ```bash
   python3 backup.py
   ```

   程序会生成 `config.json` 并提示修改。

2. **修改配置文件**

   * 填写 MCSManager 面板 API 地址、apikey、节点ID、实例ID
   * 填写 123 云盘的 `client_id` 和 `client_secret`
  > [!TIP]
  >
  > 123云盘API在[这里](https://www.123pan.com/developer)申请，理由合理基本能成功。
   * 根据需要设置 `backup.mode` 为 `cold` 或 `hot`

3. **再次运行**

   ```bash
   python3 backup.py
   ```

   程序会进入循环，按照 `config.json` 中的 `schedule.times` 定时执行备份。

---

## 备份流程

### 冷备份 (cold)
1. 调用 **MCSManager API** 停止服务器
2. 使用 `7z` 压缩服务器目录
3. **立即启动服务器**，减少停机时间
4. 在 **后台线程** 上传压缩包到 **123 云盘**

### 热备份 (hot)
1. 发送 `save-off`（关闭自动存盘）
2. 发送 `save-all`（强制写入所有区块）
3. 使用 `7z` 压缩服务器目录
4. 发送 `save-on`（恢复自动存盘）
5. 在 **后台线程** 上传压缩包到 **123 云盘**

---

## 日志

* 默认日志文件：`mc_backup.log`
* 使用 **轮转日志**，最大 10MB，保留 5 个历史文件
* 示例查看：

  ```bash
  cat mc_backup.log
  ```

---

## 定时任务

* 使用 `apscheduler` 库实现
* 格式：`HH:MM`（24小时制）
* 支持配置多个时间点，例如：

  ```json
  "times": ["03:00", "12:00", "21:00"]
  ```

脚本运行后会常驻进程，自动在这些时间点触发。

---

## 后台运行方法

推荐使用 **systemd** 或 **tmux** 管理进程。

### systemd 示例

创建服务文件 `/etc/systemd/system/mcbackup.service`：

```ini
[Unit]
Description=Minecraft Backup Service
After=network.target

[Service]
WorkingDirectory=/path/to/backup
ExecStart=/path/to/python3 /path/to/backup/backup.py
Restart=always
User=mc

[Install]
WantedBy=multi-user.target
```

启用并启动：

```bash
sudo systemctl daemon-reload
sudo systemctl enable mcbackup
sudo systemctl start mcbackup
```

---

## 注意意事项

* 上传部分使用 `pan123` SDK，内部会调用 123 云盘官方 API 进行分片上传
* 大文件上传时，服务器已提前恢复运行，不影响玩家体验
* 若上传失败，压缩包仍会保存在本地 `backup_dir`
* **建议定期检查日志文件，确认上传是否成功**