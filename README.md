# Quick Setup
```
wget https://raw.githubusercontent.com/winzzy12/vps-monitor/main/vps-monitor.sh && chmod +x vps-monitor.sh && ./vps-monitor.sh
```

# SETUP MANUAL

```
git clone https://github.com/winzzy12/vps-monitor
```
```
cd vps-monitor
```
```
nano vps-monitor.py
```
- Add Token BOT
- Add Id Chat (Group)
- Add Topic ID
Ctrl x + y

Setup Systemd

```
sudo nano /etc/systemd/system/vps-monitor.service
```
```
[Unit]
Description=vps Monitor
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/vps-monitor
ExecStart=/usr/bin/python3 /root/vps-monitor/vps-monitor.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```
systemctl daemon-reload
systemctl enable vps-monitor
systemctl start vps-monitor
systemctl status vps-monitor
```
```
systemctl restart vps-monitor
```
