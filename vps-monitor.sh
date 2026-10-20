#!/usr/bin/env bash
set -Eeuo pipefail

# VPS Monitor installer
# Creates /opt/vps-monitor/vps_monitor.py, config.json, venv and systemd service.
# No apt update/install is run by this script.

APP_DIR="/opt/vps-monitor"
SERVICE_NAME="vps-monitor"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

if [[ "${EUID}" -ne 0 ]]; then
  echo "[ERROR] Jalankan sebagai root: sudo bash $0"
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "[ERROR] python3 tidak ditemukan. Pasang Python 3 lalu jalankan ulang."
  exit 1
fi

if ! python3 -c 'import venv' >/dev/null 2>&1; then
  echo "[ERROR] Modul Python venv belum tersedia untuk $(python3 --version)."
  echo "Perbaiki APT terlebih dahulu, lalu pasang paket python3-venv."
  exit 1
fi

echo "======================================"
echo "       VPS Monitor - Installer"
echo "======================================"
echo
read -r -p "Telegram Bot Token: " BOT_TOKEN
read -r -p "Telegram Chat ID: " CHAT_ID
read -r -p "Topic ID (kosong = chat utama): " TOPIC_ID
read -r -p "Interval laporan dalam detik [300]: " INTERVAL
INTERVAL="${INTERVAL:-300}"
read -r -p "Ambang alert resource dalam persen [90]: " ALERT_THRESHOLD
ALERT_THRESHOLD="${ALERT_THRESHOLD:-90}"

if [[ -z "$BOT_TOKEN" || -z "$CHAT_ID" ]]; then
  echo "[ERROR] Bot Token dan Chat ID wajib diisi."
  exit 1
fi
if ! [[ "$INTERVAL" =~ ^[0-9]+$ ]] || (( INTERVAL < 10 )); then
  echo "[ERROR] Interval harus angka minimal 10 detik."
  exit 1
fi
if ! [[ "$ALERT_THRESHOLD" =~ ^[0-9]+$ ]] || (( ALERT_THRESHOLD < 1 || ALERT_THRESHOLD > 100 )); then
  echo "[ERROR] Ambang alert harus angka 1 sampai 100."
  exit 1
fi
if [[ -n "$TOPIC_ID" && ! "$TOPIC_ID" =~ ^[0-9]+$ ]]; then
  echo "[ERROR] Topic ID harus berupa angka atau dikosongkan."
  exit 1
fi

install -d -m 0750 "$APP_DIR"

cat > "$APP_DIR/config.json" <<CONFIG
{
  "bot_token": "$BOT_TOKEN",
  "chat_id": "$CHAT_ID",
  "topic_id": ${TOPIC_ID:-null},
  "interval": $INTERVAL,
  "alert_threshold": $ALERT_THRESHOLD
}
CONFIG
chmod 600 "$APP_DIR/config.json"

cat > "$APP_DIR/vps_monitor.py" <<'PYTHON'
#!/usr/bin/env python3
import html
import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)
    required = ("bot_token", "chat_id")
    for key in required:
        if not str(config.get(key, "")).strip():
            raise ValueError(f"Config {key} wajib diisi")
    config["interval"] = int(config.get("interval", 300))
    config["alert_threshold"] = int(config.get("alert_threshold", 90))
    topic = config.get("topic_id")
    if topic is not None and str(topic).strip():
        config["topic_id"] = int(topic)
    else:
        config["topic_id"] = None
    if config["interval"] < 10:
        raise ValueError("Interval minimal 10 detik")
    if not 1 <= config["alert_threshold"] <= 100:
        raise ValueError("alert_threshold harus 1 sampai 100")
    return config


CONFIG = load_config()
BOT_TOKEN = CONFIG["bot_token"]
CHAT_ID = str(CONFIG["chat_id"])
TOPIC_ID = CONFIG["topic_id"]
INTERVAL = CONFIG["interval"]
ALERT_THRESHOLD = CONFIG["alert_threshold"]


def send_telegram(text, parse_mode="HTML"):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    if TOPIC_ID is not None:
        payload["message_thread_id"] = TOPIC_ID

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        if not result.get("ok"):
            print(f"[TELEGRAM ERR] {result.get('description', 'Unknown error')}", flush=True)
        return result
    except urllib.error.HTTPError as e:
        try:
            error_body = e.read().decode("utf-8")
        except Exception:
            error_body = str(e)
        print(f"[TELEGRAM HTTP ERR] {e.code}: {error_body}", flush=True)
        return None
    except Exception as e:
        print(f"[TELEGRAM ERR] {e}", flush=True)
        return None


def run_cmd(cmd):
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip() if result.returncode == 0 else "?"
    except Exception:
        return "?"


def get_metrics():
    hostname = socket.gethostname()

    ip_public = "?"
    for ip_url in ("https://api.ipify.org", "https://icanhazip.com"):
        try:
            req = urllib.request.Request(
                ip_url, headers={"User-Agent": "VPS-Monitor/1.0"}
            )
            with urllib.request.urlopen(req, timeout=8) as response:
                ip_public = response.read().decode().strip()
            if ip_public:
                break
        except Exception:
            continue
    if not ip_public or ip_public == "?":
        ip_public = run_cmd("curl -s --max-time 5 https://api.ipify.org") or "?"

    uptime_raw = run_cmd("cat /proc/uptime")
    try:
        uptime_sec = float(uptime_raw.split()[0])
        days = int(uptime_sec // 86400)
        hours = int((uptime_sec % 86400) // 3600)
        mins = int((uptime_sec % 3600) // 60)
        uptime_str = f"{days}d {hours}h {mins}m"
    except Exception:
        uptime_str = run_cmd("uptime -p") or "?"

    try:
        mem = run_cmd("free -m | awk '/^Mem:/ {print $2, $3, $4, $7}'")
        parts = mem.split()
        ram_total, ram_used, ram_free, ram_avail = map(int, parts[:4])
        ram_pct = round((ram_used / ram_total) * 100, 1) if ram_total else 0
    except Exception:
        ram_total = ram_used = ram_free = ram_avail = 0
        ram_pct = 0

    cpu_raw = run_cmd("top -bn1 | grep -E 'Cpu\\(s\\)|%Cpu' | head -n1 | awk '{print $2+$4}'")
    try:
        cpu_pct = round(float(cpu_raw), 1)
    except Exception:
        cpu_pct = 0

    load_parts = run_cmd("cat /proc/loadavg").split()
    load_1 = load_parts[0] if len(load_parts) > 0 else "?"
    load_5 = load_parts[1] if len(load_parts) > 1 else "?"
    load_15 = load_parts[2] if len(load_parts) > 2 else "?"

    disk_info = run_cmd("df -h / | awk 'NR==2 {print $3 \"/\" $2 \" (\" $5 \")\"}'") or "?"
    disk_raw = run_cmd("df -P / | awk 'NR==2 {print $5}' | tr -d '%'")
    try:
        disk_pct = int(disk_raw)
    except Exception:
        disk_pct = 0

    try:
        user_count = int(run_cmd("who | wc -l"))
    except Exception:
        user_count = 0
    users_list = run_cmd("who | awk '{print $1}' | sort -u | tr '\\n' ' '") or "(none)"

    return {
        "hostname": hostname,
        "ip_public": ip_public,
        "uptime": uptime_str,
        "ram_total": ram_total,
        "ram_used": ram_used,
        "ram_free": ram_free,
        "ram_avail": ram_avail,
        "ram_pct": ram_pct,
        "cpu_pct": cpu_pct,
        "load_1": load_1,
        "load_5": load_5,
        "load_15": load_15,
        "disk_pct": disk_pct,
        "disk_info": disk_info,
        "user_count": user_count,
        "users_list": users_list,
    }


def make_bar(pct, length=10):
    try:
        pct = max(0, min(100, float(pct)))
    except (ValueError, TypeError):
        pct = 0
    filled = round(pct / 100 * length)
    return "█" * filled + "░" * (length - filled)


def format_status(m, alert=False):
    prefix = "🚨 <b>ALERT! Resource High Usage!</b>\n\n" if alert else ""
    bar_ram = make_bar(m["ram_pct"])
    bar_cpu = make_bar(m["cpu_pct"])
    bar_disk = make_bar(m["disk_pct"])

    hostname = html.escape(str(m["hostname"]))
    ip_public = html.escape(str(m["ip_public"]))
    uptime = html.escape(str(m["uptime"]))
    users_list = html.escape(str(m["users_list"]))
    disk_info = html.escape(str(m["disk_info"]))

    status = (
        f"{prefix}"
        f"<b>🖥 VPS Monitor — {hostname}</b>\n"
        f"├─ 🌐 IP Public: <code>{ip_public}</code>\n"
        f"├─ ⏱ Uptime: {uptime}\n"
        f"├─ 👥 User Login: {m['user_count']} ({users_list})\n"
        f"│\n"
        f"├─ 💾 <b>RAM</b> {m['ram_used']}/{m['ram_total']} MB "
        f"{bar_ram} <b>{m['ram_pct']}%</b>\n"
        f"├─ 🖧 Available: {m['ram_avail']} MB\n"
        f"│\n"
        f"├─ ⚡ <b>CPU</b> {bar_cpu} <b>{m['cpu_pct']}%</b>\n"
        f"├─ 📊 Load: {m['load_1']} / {m['load_5']} / {m['load_15']}\n"
        f"│\n"
        f"├─ 💿 <b>DISK</b> {bar_disk} <b>{m['disk_pct']}%</b>\n"
        f"└─ 📁 {disk_info}"
    )

    alerts = []
    if m["ram_pct"] >= ALERT_THRESHOLD:
        alerts.append(f"🚨 RAM {m['ram_pct']}% >= {ALERT_THRESHOLD}%")
    if m["cpu_pct"] >= ALERT_THRESHOLD:
        alerts.append(f"🚨 CPU {m['cpu_pct']}% >= {ALERT_THRESHOLD}%")
    if m["disk_pct"] >= ALERT_THRESHOLD:
        alerts.append(f"🚨 DISK {m['disk_pct']}% >= {ALERT_THRESHOLD}%")
    if alerts:
        status += "\n\n" + "\n".join(alerts)
    return status


def main():
    destination = f"topic {TOPIC_ID}" if TOPIC_ID is not None else "chat utama (tanpa topic)"
    print(
        f"[VPS Monitor] Started | Interval: {INTERVAL}s "
        f"({INTERVAL // 60} menit) | Destination: {destination}",
        flush=True,
    )
    while True:
        try:
            metrics = get_metrics()
            alert = any(
                metrics[key] >= ALERT_THRESHOLD
                for key in ("ram_pct", "cpu_pct", "disk_pct")
            )
            result = send_telegram(format_status(metrics, alert=alert))
            if result and result.get("ok"):
                print(f"[OK] Status sent to {destination} (alert={alert})", flush=True)
            else:
                description = result.get("description", "Unknown error") if result else "Request failed"
                print(f"[FAIL] {description}", flush=True)
        except Exception as e:
            print(f"[ERR] {e}", flush=True)
        try:
            time.sleep(INTERVAL)
        except KeyboardInterrupt:
            print("\n[VPS Monitor] Stopped.", flush=True)
            break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[VPS Monitor] Stopped.", flush=True)
PYTHON
chmod 750 "$APP_DIR/vps_monitor.py"

if [[ ! -x "$APP_DIR/venv/bin/python" ]]; then
  python3 -m venv "$APP_DIR/venv"
fi

cat > "$SERVICE_FILE" <<SERVICE
[Unit]
Description=VPS Resource Monitor Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/python $APP_DIR/vps_monitor.py
Restart=always
RestartSec=10
User=root
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
SERVICE
chmod 644 "$SERVICE_FILE"

systemctl daemon-reload
systemctl enable --now "$SERVICE_NAME"

echo
echo "[OK] VPS Monitor berhasil dipasang."
echo "Folder   : $APP_DIR"
echo "Config   : $APP_DIR/config.json"
echo "Service  : $SERVICE_NAME"
echo
systemctl --no-pager --full status "$SERVICE_NAME" || true
echo
echo "Perintah berguna:"
echo "  systemctl status $SERVICE_NAME"
echo "  journalctl -u $SERVICE_NAME -f"
echo "  systemctl restart $SERVICE_NAME"
echo "  nano $APP_DIR/config.json   # edit konfigurasi; lalu restart service"
