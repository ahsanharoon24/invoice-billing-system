# 🚀 Deployment Guide — Invoice & Billing Management System (Production)

**Architecture (recommended):** poora app ek DigitalOcean VPS par — Gunicorn + Nginx + HTTPS.
Yeh monolith app hai (Flask templates + backend ek saath) — **Vercel is app ke liye nahi chahiye**
(Vercel sirf alag marketing site ke liye hota hai).

```
User browser
     │
     ▼
https://billing.junaidnazirpofwah.site   (Namecheap DNS: A record → VPS IP)
     │
     ▼
Nginx (443/80, SSL via Certbot)
     │
     ▼
Gunicorn (127.0.0.1:5000, systemd service)
     │
     ▼
Flask app + SQLite (invoices.db) + backups/ + static/uploads
```

---

## Phase 0 — Local prep (Windows, ek dafa)

1. Project folder: `C:\Users\Jadoon\Desktop\Invoice\clean_capital_billing`
2. Code deployment-ready hai: `wsgi.py` (Gunicorn entry), `db.py` (busy_timeout), `requirements.txt` (flask + gunicorn)
3. Deploy zip banayein (venv, __pycache__, invoices.db, backups NAHI include):

```bash
cd C:\Users\Jadoon\Desktop\Invoice\clean_capital_billing
# zip banane ke liye (PowerShell):
Compress-Archive -Path app.py,clients.py,invoices.py,reports.py,settings_users.py,decorators.py,db.py,utils.py,wsgi.py,schema.sql,requirements.txt,launcher.py,run.bat,README.md,templates,static -DestinationPath deploy.zip
```

> 💡 **Local data migrate karni hai?** `invoices.db` bhi zip mein daal dein — server pe pehli baar use hogi.
> Nahi to server fresh start hoga (sirf admin account).

---

## Phase 1 — DigitalOcean Droplet

1. **Create Droplet:** Ubuntu 22.04 (ya 24.04), basic plan ($6/mo kafi hai — SQLite + chand users), koi bhi region
2. **Root password / SSH key** save karein
3. SSH login:
```bash
ssh root@SERVER_IP
```

---

## Phase 2 — Server setup (root)

```bash
# 1. Update
sudo apt update && sudo apt -y upgrade

# 2. Python + tools
sudo apt install -y python3 python3-dev python3-venv build-essential nginx

# 3. Dedicated user (root mein app nahi chalate)
sudo adduser billing            # password set karein
sudo usermod -aG sudo billing

# 4. Firewall — PEHLE SSH allow karein, phir enable (warna lock out!)
sudo ufw allow OpenSSH
sudo ufw allow 80
sudo ufw allow 443
sudo ufw enable
sudo ufw status
```

---

## Phase 3 — App files

```bash
# billing user ban kar switch
su - billing

# project folder
mkdir ~/app && cd ~/app
```

**deploy.zip upload karein** (local Windows se, apne terminal mein):
```bash
scp C:\Users\Jadoon\Desktop\Invoice\clean_capital_billing\deploy.zip billing@SERVER_IP:~/app/
```

```bash
# server pe wapas (billing user)
cd ~/app
unzip deploy.zip
python3 -m venv venv
venv/bin/pip install -r requirements.txt

# test — app chal raha hai?
venv/bin/gunicorn -w 2 -b 127.0.0.1:5000 wsgi:app --timeout 60
# Ctrl+C band karein, phir systemd service banayenge
```

> **Workers:** `-w 2` rakhein (SQLite single-writer hai, zyada workers locking issues de sakte hain).

---

## Phase 4 — Systemd service (auto-start + restart)

```bash
sudo nano /etc/systemd/system/gunicorn.service
```

```ini
[Unit]
Description=Gunicorn - Invoice Billing System
After=network.target

[Service]
User=billing
Group=billing
WorkingDirectory=/home/billing/app
Environment=SECRET_KEY=YAHAN_BOHUT_LAMBA_RANDOM_STRING_DAALEIN
ExecStart=/home/billing/app/venv/bin/gunicorn -w 2 -b 127.0.0.1:5000 --timeout 60 wsgi:app
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable gunicorn
sudo systemctl start gunicorn
sudo systemctl status gunicorn      # active (running) hona chahiye
journalctl -u gunicorn -e           # agar issue ho to logs
```

> **SECRET_KEY banane ka tarika:** `python3 -c "import secrets; print(secrets.token_hex(32))"` — woh value paste karein.
> Is ke bina sessions insecure honge.

---

## Phase 5 — Nginx reverse proxy

```bash
sudo nano /etc/nginx/sites-available/billing
```

```nginx
server {
    listen 80;
    server_name billing.junaidnazirpofwah.site;

    client_max_body_size 8M;   # logo/signature upload ke liye

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }

    location /static {
        alias /home/billing/app/static;
        expires 7d;
    }
}
```

```bash
sudo rm -f /etc/nginx/sites-enabled/default
sudo ln -s /etc/nginx/sites-available/billing /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

---

## Phase 6 — SSL (HTTPS) via Certbot

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d billing.junaidnazirpofwah.site
# prompt par "2" (redirect HTTP→HTTPS) select karein

# auto-renew test:
sudo certbot renew --dry-run
```

> Ubuntu par auto-renew khud chalta hai (systemd timer). Koi cron zaroori nahi.

---

## Phase 7 — DNS (Namecheap)

1. Namecheap → **Domain List → Manage → Advanced DNS**
2. Records (replace example IP with your droplet IP):

| Type | Host | Value |
|---|---|---|
| A | billing | `YOUR_DROPLET_IP` |
| A | @ | `76.76.21.21` *(sirf agar Vercel marketing site hai — optional)* |
| CNAME | www | `cname.vercel-dns.com` *(optional)* |

3. Propagation wait (kuch minutes se 24h tak):
```bash
nslookup billing.junaidnazirpofwah.site
```

---

## Phase 8 — Verify

1. Browser: `https://billing.junaidnazirpofwah.site`
2. Login: `admin` / `admin123`
3. **Turant password change karein** (🔑 Password menu)
4. ⚙️ Company → company info, bank, GST%, logo set karein
5. Test: client add → invoice → print/PDF → next-month → payment

---

## Phase 9 — Backups (production mein zaroori)

App khud har 24h mein backup banata hai (`backups/` folder, last 30).

**Server se door backup** (droplet delete ho jaye to bhi data safe) — cron:

```bash
crontab -e
# har roz 2:00 AM par backup server se nikaal kar rakhna (manual download ke liye)
0 2 * * * cd /home/billing/app && tar -czf ~/backup-$(date +\%Y\%m\%d).tar.gz invoices.db backups/ static/uploads
```

Best practice: har hafte manually `~/backup-*.tar.gz` download karein apne PC / Google Drive par.

---

## 🔧 Troubleshooting

| Problem | Check |
|---|---|
| 502 Bad Gateway | `sudo systemctl status gunicorn` — service down? `journalctl -u gunicorn -e` |
| App chal raha hai, 502 | Nginx proxy_pass sahi? `sudo tail -f /var/log/nginx/error.log` |
| Static images nahi dikhte | Nginx `location /static` alias path sahi? |
| "Address already in use" | Koi purana gunicorn: `sudo pkill gunicorn` phir `sudo systemctl restart gunicorn` |
| Session logout ho jata hai | SECRET_KEY systemd mein set hai? (badalte hi sessions invalid hote hain) |
| Database locked | Workers 2 se zyada hain? `PRAGMA busy_timeout` db.py mein already set hai |
| Backups folder mehfile nahi | `ls -la /home/billing/app/backups` — billing user ko write permission hai? |

---

## 🔒 Security checklist

- [ ] `admin` password change (deployment ke turant baad)
- [ ] SECRET_KEY env set (long random)
- [ ] HTTPS active (certbot)
- [ ] Firewall: sirf 22/80/443
- [ ] Root se app nahi chal rahi (billing user)
- [ ] Regular backups + off-server copy
- [ ] Staff ke liye alag users (Viewer/Billing Officer roles)
