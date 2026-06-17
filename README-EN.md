# Welcome to this Project!

## What is this?
A Minecraft server automated backup tool based on **Python + MCSManager API + 123Pan Cloud Drive API**.

Features:
- Automatically generates `config.json` on first run
- Supports two backup modes:
  - **Cold backup (cold)**: stop server → compress → start server
  - **Hot backup (hot)**: save-off → save-all → compress world folder → save-on (no shutdown required)
- Uses `7z` to compress the server directory
- Server resumes normal operation immediately after compression, while **uploading runs in a background thread**
- Uploads to **123Pan Cloud Drive** (via official Open Platform API)
- Supports multiple scheduled **backup times**
- Supports **log rotation** for long-term stability

---

## Requirements

- Operating System: Linux  
- Python version: `>= 3.8`  
- UV
- [MCSManager Panel](https://mcsmanager.com/)  
- System dependencies:
```bash
sudo apt update && sudo apt install p7zip-full
```

- Python dependencies:

```bash
uv sync
```

---

## Configuration File (`config.json`)

The script will automatically generate a sample config file on the first run and exit.
You need to manually modify it.

```json
{
  "mcsmanager": {
    "base_url": "http://panel.example.com", 
    "apikey": "YOUR_MCSM_APIKEY",
    "daemonId": "your-daemon-id",
    "instance_uuid": "your-instance-uuid"
  },
  "server": {
    "server_dir": "/home/mc/server",
    "backup_dir": "/home/mc/backups",
    "compress_cmd": "7z",
    "compress_args": ["a", "-mx=9"]
  },
  "123pan_http": {
    "api_base_url": "https://open-api.123pan.com",
    "client_id": "YOUR_123PAN_CLIENT_ID",
    "client_secret": "YOUR_123PAN_CLIENT_SECRET",
    "parent_folder_id": 0
  },
  "schedule": {
    "times": ["03:00", "15:00"],
    "timezone": "Asia/Shanghai"
  },
  "logging": {
    "log_file": "mc_backup.log",
    "max_bytes": 10485760,
    "backup_count": 5
  },
  "backup": {
    "mode": "cold",
    "keep_days": 7,
    "keep_count": 10,
    "storage": "both"
  }
}
```

**Note: Version 2.x configuration format has changed. The above sample is for version 2.x.**

---

## Usage

### 1. First run

```bash
python3 backup.py
```

This creates `config.json` and exits.

### 2. Edit the configuration file

* Fill in the MCSManager API address, apikey, node ID, instance ID
* Provide the `client_id` and `client_secret` for 123Pan
> [!TIP]
>
> You can apply for 123Pan API at: [https://www.123pan.com/developer](https://www.123pan.com/developer)
* Choose `cold` or `hot` backup mode

### 3. Run again

```bash
python3 backup.py
```

The program will stay running and trigger backups according to `schedule.times`.

---

## Backup Process

### Cold Backup (cold)

1. Stop server via **MCSManager API**
2. Compress server directory using `7z`
3. **Restart server immediately**
4. Upload compressed file to **123Pan** in a background thread

### Hot Backup (hot)

1. Send `save-off`
2. Send `save-all`
3. Compress server directory
4. Send `save-on`
5. Upload in background

---

## Logs

* Default log file: `mc_backup.log`
* Rotates when size exceeds 10MB, keeping 5 older logs
* Check logs:

  ```bash
  cat mc_backup.log
  ```

---

## Scheduled Tasks

* Implemented using `apscheduler`
* Time format: `HH:MM` (24-hour)
* Supports multiple backup times:

  ```json
  "times": ["03:00", "12:00", "21:00"]
  ```

The script remains running and triggers at these times.

---

## Running in Background

You may use **systemd** or **tmux**.

### Example systemd service

Create `/etc/systemd/system/mcbackup.service`:

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

Activate service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable mcbackup
sudo systemctl start mcbackup
```

---

## Notes

* The uploading process uses the `pan123` SDK, which calls the 123Pan official API for multipart uploads
* For large files, the server will already be back online while uploading
* If upload fails, the compressed backup still remains in `backup_dir`
* **Check log files periodically to confirm upload success**

---

## Contributing

If you'd like to contribute, it's recommended to use [VS Code](https://code.visualstudio.com/).
Please submit PRs to the **dev** branch.

---

## Issue Feedback

Report issues here:
[https://github.com/xhdndmm/mcbackup/issues](https://github.com/xhdndmm/mcbackup/issues)

---

## License

This project is licensed under the **GPLv3** license:
[https://www.gnu.org/licenses/gpl-3.0.html](https://www.gnu.org/licenses/gpl-3.0.html)

---
Translated by ChatGPT