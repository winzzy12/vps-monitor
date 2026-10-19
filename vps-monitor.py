```python
#!/usr/bin/env python3
"""
VPS Monitor — Kirim status VPS + alert ke Telegram setiap 5 menit.
Cek: IP public, uptime, RAM/CPU/disk usage, user login.
Alert jika usage >= 90%.
TOPIC_ID bersifat optional.
"""

import json
import socket
import subprocess
import time
import urllib.request
import urllib.error
import html

# ==================================================
# CONFIG
# ==================================================

BOT_TOKEN = "TOKENBOTMU"
CHAT_ID = "IDCHATMU"

TOPIC_ID = None
# None = kirim ke chat utama tanpa topic
# TOPIC_ID = 285  # Isi ID topic jika ingin mengirim ke topic tertentu

ALERT_THRESHOLD = 90  # persen
INTERVAL = 300         # 300 detik = 5 menit


# ==================================================
# TELEGRAM
# ==================================================

def send_telegram(text, parse_mode="HTML"):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }

    # Tambahkan message_thread_id hanya jika topic diisi
    if TOPIC_ID is not None and str(TOPIC_ID).strip():
        try:
            payload["message_thread_id"] = int(TOPIC_ID)
        except (ValueError, TypeError):
            print("[CONFIG ERR] TOPIC_ID harus berupa angka atau None", flush=True)
            return None

    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data,
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


# ==================================================
# SYSTEM COMMAND
# ==================================================

def run_cmd(cmd):
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return "?"
    except Exception:
        return "?"


# ==================================================
# VPS METRICS
# ==================================================

def get_metrics():
    hostname = socket.gethostname()

    # IP Public
    ip_public = "?"
    for ip_url in (
        "https://api.ipify.org",
        "https://icanhazip.com",
    ):
        try:
            req = urllib.request.Request(
                ip_url,
                headers={"User-Agent": "VPS-Monitor/1.0"},
            )
            with urllib.request.urlopen(req, timeout=8) as response:
                ip_public = response.read().decode().strip()

            if ip_public:
                break
        except Exception:
            continue

    if not ip_public or ip_public == "?":
        ip_public = run_cmd(
            "curl -s --max-time 5 https://api.ipify.org"
        ) or "?"

    # Uptime
    uptime_raw = run_cmd("cat /proc/uptime")

    try:
        uptime_sec = float(uptime_raw.split()[0])
        days = int(uptime_sec // 86400)
        hours = int((uptime_sec % 86400) // 3600)
        mins = int((uptime_sec % 3600) // 60)
        uptime_str = f"{days}d {hours}h {mins}m"
    except Exception:
        uptime_str = run_cmd("uptime -p") or "?"

    # RAM
    try:
        mem = run_cmd(
            "free -m | awk '/^Mem:/ {print $2, $3, $4, $7}'"
        )
        parts = mem.split()

        ram_total = int(parts[0])
        ram_used = int(parts[1])
        ram_free = int(parts[2])
        ram_avail = int(parts[3])

        ram_pct = round((ram_used / ram_total) * 100, 1) if ram_total else 0

    except Exception:
        ram_total = 0
        ram_used = 0
        ram_free = 0
        ram_avail = 0
        ram_pct = 0

    # CPU usage
    cpu_raw = run_cmd(
        "top -bn1 | grep 'Cpu(s)' | awk '{print $2+$4}'"
    )

    try:
        cpu_pct = round(float(cpu_raw), 1)
    except Exception:
        cpu_pct = 0

    # CPU Load Average
    load_raw = run_cmd("cat /proc/loadavg")
    load_parts = load_raw.split()

    load_1 = load_parts[0] if len(load_parts) > 0 else "?"
    load_5 = load_parts[1] if len(load_parts) > 1 else "?"
    load_15 = load_parts[2] if len(load_parts) > 2 else "?"

    # Disk
    disk_info = run_cmd(
        "df -h / | awk 'NR==2 {print $3 \"/\" $2 \" (\" $5 \")\"}'"
    ) or "?"

    disk_raw = run_cmd(
        "df -P / | awk 'NR==2 {print $5}' | tr -d '%'"
    )

    try:
        disk_pct = int(disk_raw)
    except Exception:
        disk_pct = 0

    # Current user login sessions
    user_count_raw = run_cmd("who | wc -l")

    try:
        user_count = int(user_count_raw)
    except Exception:
        user_count = 0

    # Unique logged-in usernames
    users_list = run_cmd(
        "who | awk '{print $1}' | sort -u | tr '\\n' ' '"
    ) or "(none)"

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


# ==================================================
# PROGRESS BAR
# ==================================================

def make_bar(pct, length=10):
    try:
        pct = max(0, min(100, float(pct)))
    except (ValueError, TypeError):
        pct = 0

    filled = round(pct / 100 * length)
    empty = length - filled

    return "█" * filled + "░" * empty


# ==================================================
# FORMAT STATUS MESSAGE
# ==================================================

def format_status(m, alert=False):
    """Format status VPS menjadi pesan Telegram HTML."""

    prefix = (
        "🚨 <b>ALERT! Resource High Usage!</b>\n\n"
        if alert else ""
    )

    bar_ram = make_bar(m["ram_pct"])
    bar_cpu = make_bar(m["cpu_pct"])
    bar_disk = make_bar(m["disk_pct"])

    # Escape data sistem agar tidak merusak format HTML Telegram
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
        f"├─ ⚡ <b>CPU</b> {bar_cpu} "
        f"<b>{m['cpu_pct']}%</b>\n"
        f"├─ 📊 Load: {m['load_1']} / {m['load_5']} / {m['load_15']}\n"
        f"│\n"
        f"├─ 💿 <b>DISK</b> {bar_disk} "
        f"<b>{m['disk_pct']}%</b>\n"
        f"└─ 📁 {disk_info}"
    )

    # Alert spesifik untuk resource yang melewati threshold
    alerts = []

    if m["ram_pct"] >= ALERT_THRESHOLD:
        alerts.append(
            f"🚨 RAM {m['ram_pct']}% >= {ALERT_THRESHOLD}%"
        )

    if m["cpu_pct"] >= ALERT_THRESHOLD:
        alerts.append(
            f"🚨 CPU {m['cpu_pct']}% >= {ALERT_THRESHOLD}%"
        )

    if m["disk_pct"] >= ALERT_THRESHOLD:
        alerts.append(
            f"🚨 DISK {m['disk_pct']}% >= {ALERT_THRESHOLD}%"
        )

    if alerts:
        status += "\n\n" + "\n".join(alerts)

    return status


# ==================================================
# MAIN LOOP
# ==================================================

def main():
    destination = (
        f"topic {TOPIC_ID}"
        if TOPIC_ID is not None and str(TOPIC_ID).strip()
        else "chat utama (tanpa topic)"
    )

    print(
        f"[VPS Monitor] Started | Interval: {INTERVAL}s "
        f"({INTERVAL // 60} menit) | Destination: {destination}",
        flush=True,
    )

    while True:
        try:
            metrics = get_metrics()

            alert = (
                metrics["ram_pct"] >= ALERT_THRESHOLD
                or metrics["cpu_pct"] >= ALERT_THRESHOLD
                or metrics["disk_pct"] >= ALERT_THRESHOLD
            )

            message = format_status(metrics, alert=alert)
            result = send_telegram(message)

            if result and result.get("ok"):
                print(
                    f"[OK] Status sent to {destination} "
                    f"(alert={alert})",
                    flush=True,
                )
            else:
                description = (
                    result.get("description", "Unknown error")
                    if result else "Request failed"
                )
                print(f"[FAIL] {description}", flush=True)

        except KeyboardInterrupt:
            print("\n[VPS Monitor] Stopped.", flush=True)
            break

        except Exception as e:
            print(f"[ERR] {e}", flush=True)

        try:
            time.sleep(INTERVAL)
        except KeyboardInterrupt:
            print("\n[VPS Monitor] Stopped.", flush=True)
            break


if __name__ == "__main__":
    main()
```
