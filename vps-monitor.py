#!/usr/bin/env python3
"""
VPS Monitor — Kirim status VPS + alert ke Telegram setiap 5 menit.
Cek: IP public, uptime, RAM/CPU/disk usage, user login.
Alert jika usage >= 90%.
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

# === CONFIG ===
BOT_TOKEN = "TOKENBOTMU"
CHAT_ID = "IDCHATMU"
TOPIC_ID = TOPIC_ID
ALERT_THRESHOLD = 90  # persen
INTERVAL = 300  # 3 menit

# === TELEGRAM ===
def send_telegram(text, parse_mode="HTML"):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
        "message_thread_id": TOPIC_ID,
        "disable_web_page_preview": True,
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data,
        headers={"Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return json.loads(resp.read())
    except Exception as e:
        print(f"[TELEGRAM ERR] {e}", flush=True)
        return None


def run_cmd(cmd):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        return r.stdout.strip()
    except:
        return "?"


def get_metrics():
    hostname = socket.gethostname()

    # IP Public
    ip_public = "?"
    try:
        req = urllib.request.Request("https://api.ipify.org", headers={"User-Agent": "curl/8"})
        ip_public = urllib.request.urlopen(req, timeout=10).read().decode().strip()
    except:
        try:
            req = urllib.request.Request("https://icanhazip.com", headers={"User-Agent": "curl/8"})
            ip_public = urllib.request.urlopen(req, timeout=10).read().decode().strip()
        except:
            ip_public = run_cmd("curl -s --max-time 5 https://api.ipify.org")

    # Uptime
    uptime_raw = run_cmd("cat /proc/uptime")
    try:
        uptime_sec = float(uptime_raw.split()[0])
        days = int(uptime_sec // 86400)
        hours = int((uptime_sec % 86400) // 3600)
        mins = int((uptime_sec % 3600) // 60)
        uptime_str = f"{days}d {hours}h {mins}m"
    except:
        uptime_str = run_cmd("uptime -p") or "?"

    # RAM
    try:
        mem = run_cmd("free -m | awk '/Mem:/ {print $2, $3, $4, $7}'")
        parts = mem.split()
        ram_total = int(parts[0])
        ram_used = int(parts[1])
        ram_free = int(parts[2])
        ram_avail = int(parts[3])
        ram_pct = round((ram_used / ram_total) * 100, 1)
    except:
        ram_total = ram_used = ram_avail = 0
        ram_pct = 0

    # CPU
    cpu_pct = run_cmd("top -bn1 | grep 'Cpu(s)' | awk '{print $2+$4}'")
    try:
        cpu_pct = round(float(cpu_pct), 1)
    except:
        cpu_pct = 0

    # CPU Load Average
    load_raw = run_cmd("cat /proc/loadavg")
    load_parts = load_raw.split()
    load_1 = load_parts[0] if load_parts else "?"
    load_5 = load_parts[1] if len(load_parts) > 1 else "?"
    load_15 = load_parts[2] if len(load_parts) > 2 else "?"

    # Disk
    disk_info = run_cmd("df -h / | awk 'NR==2 {print $3\"/\"$2\" (\"$5\")\"}'") or "?"
    disk_pct = run_cmd("df -h / | awk 'NR==2 {print $5}' | tr -d '%'")
    try:
        disk_pct = int(disk_pct)
    except:
        disk_pct = 0

    # Total user login (current sessions)
    user_count = run_cmd("who | wc -l")
    try:
        user_count = int(user_count)
    except:
        user_count = 0

    # Users list
    users_list = run_cmd("who | awk '{print $1}' | sort -u | tr '\\n' ' '") or "(none)"

    return {
        "hostname": hostname,
        "ip_public": ip_public,
        "uptime": uptime_str,
        "ram_total": ram_total,
        "ram_used": ram_used,
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


def format_status(m, alert=False):
    """Buat pesan status VPS."""
    prefix = "🚨 <b>ALERT! Resource High Usage!</b>\n\n" if alert else ""
    bar_ram = make_bar(m["ram_pct"])
    bar_cpu = make_bar(m["cpu_pct"])
    bar_disk = make_bar(m["disk_pct"])

    status = (
        f"{prefix}"
        f"<b>🖥 VPS Monitor — {m['hostname']}</b>\n"
        f"├─ 🌐 IP Public: <code>{m['ip_public']}</code>\n"
        f"├─ ⏱ Uptime: {m['uptime']}\n"
        f"├─ 👥 User Login: {m['user_count']} ({m['users_list']})\n"
        f"│\n"
        f"├─ 💾 <b>RAM</b>  {m['ram_used']}/{m['ram_total']}MB  {bar_ram}  <b>{m['ram_pct']}%</b>\n"
        f"├─ 🖧 Avail: {m['ram_avail']}MB\n"
        f"│\n"
        f"├─ ⚡ <b>CPU</b>  {bar_cpu}  <b>{m['cpu_pct']}%</b>\n"
        f"├─ 📊 Load: {m['load_1']} / {m['load_5']} / {m['load_15']}\n"
        f"│\n"
        f"├─ 💿 <b>DISK</b>  {bar_disk}  <b>{m['disk_pct']}%</b>\n"
        f"└─ 📁 {m['disk_info']}"
    )

    # Tambah alert spesifik
    alerts = []
    if m["ram_pct"] >= ALERT_THRESHOLD:
        alerts.append(f"🚨 RAM {m['ram_pct']}% ≥ {ALERT_THRESHOLD}%")
    if m["cpu_pct"] >= ALERT_THRESHOLD:
        alerts.append(f"🚨 CPU {m['cpu_pct']}% ≥ {ALERT_THRESHOLD}%")
    if m["disk_pct"] >= ALERT_THRESHOLD:
        alerts.append(f"🚨 DISK {m['disk_pct']}% ≥ {ALERT_THRESHOLD}%")

    if alerts:
        status += "\n\n" + "\n".join(alerts)

    return status


def make_bar(pct, length=10):
    """Buat progress bar Unicode."""
    pct = max(0, min(100, pct))
    filled = round(pct / 100 * length)
    empty = length - filled
    bar = "█" * filled + "░" * empty
    return bar


def main():
    print(f"[VPS Monitor] Started. Interval: {INTERVAL} detik ({INTERVAL//60} menit)", flush=True)
    while True:
        try:
            m = get_metrics()
            alert = (m["ram_pct"] >= ALERT_THRESHOLD or
                     m["cpu_pct"] >= ALERT_THRESHOLD or
                     m["disk_pct"] >= ALERT_THRESHOLD)

            msg = format_status(m, alert=alert)
            result = send_telegram(msg)
            if result and result.get("ok"):
                print(f"[OK] Status sent to topic 285 (alert={alert})", flush=True)
            else:
                desc = result.get("description") if result else "unknown"
                print(f"[FAIL] {desc}", flush=True)
        except Exception as e:
            print(f"[ERR] {e}", flush=True)

        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
