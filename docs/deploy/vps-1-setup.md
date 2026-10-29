# VPS 1 — Setup Dashboard (Frontend)

> Panduan dan catatan status setup VPS 1 (`clau-vps1`), server untuk frontend Next.js. Keputusan dasar ada di [`../post-vps-checklist.md`](../post-vps-checklist.md). IP server **tidak** ditulis di repo; gunakan `<IP_VPS_1>`.

## 0. VPS baru / pengganti: satu perintah (2026-10-18)

VPS 1 **tidak menyimpan data atau secret** (database dan login ada di VPS 2), jadi mengganti VPS 1 tidak perlu memulihkan apa pun. Semua yang ada di § 3–8 dipasang oleh `scripts/deploy/vps1-setup.sh`: update sistem, Node.js 22, Nginx yang dikeraskan, firewall (hanya 22/80/443), SSH tanpa root/password, fail2ban, update keamanan + reboot otomatis 03:30 WITA, swap, user khusus `clau-web` & `clau-deploy`, rilis pertama dari `release/vps1`, deploy otomatis tiap 5 menit, cek, dan backup config mingguan. Aman diulang di VPS yang sudah jalan.

Total ±20 menit. Login ke VPS baru, paste **satu perintah per baris**.

**1. User admin `dea` + SSH key** (sebagai `root`, sekali; lewati bila `ssh dea@<IP_VPS_BARU>` sudah bisa):

```bash
adduser dea
usermod -aG sudo dea
mkdir -p /home/dea/.ssh
cp /root/.ssh/authorized_keys /home/dea/.ssh/
chown -R dea:dea /home/dea/.ssh
chmod 700 /home/dea/.ssh
chmod 600 /home/dea/.ssh/authorized_keys
```

Keluar, lalu login lagi sebagai `ssh dea@<IP_VPS_BARU>`. Langkah berikutnya sebagai `dea`.

**2. Tailscale** (nama `clau-vps1`):

```bash
curl -fsSL https://tailscale.com/install.sh -o /tmp/tailscale-install.sh
sudo sh /tmp/tailscale-install.sh
sudo tailscale up --hostname=clau-vps1
```

Buka link yang muncul dan login dengan akun Tailscale owner. Di [admin Tailscale](https://login.tailscale.com/admin/machines): hapus mesin VPS 1 lama bila masih ada (supaya nama `clau-vps1` tidak jadi `clau-vps1-1`), lalu pada `clau-vps1` pilih **Disable key expiry**.

**3. Setup** (±10–15 menit, build pertama paling lama):

```bash
curl -fsSL https://raw.githubusercontent.com/deakasep/agent/main/scripts/deploy/vps1-setup.sh -o /tmp/vps1-setup.sh
sudo bash /tmp/vps1-setup.sh
```

Hasil akhir = daftar `clau-vps1-check`; yang wajib: **0 gagal**. Dashboard tampil di `http://<IP_VPS_BARU>`.

**4. Sesudahnya:** matikan/hapus VPS lama di panel provider. Bila nanti ada domain, arahkan DNS ke IP baru.

Bila script berhenti dengan `GAGAL: ...`, jalankan ulang perintah `sudo bash /tmp/vps1-setup.sh` setelah penyebabnya diperbaiki (pesan menyebut langkahnya), atau kirim outputnya ke agent.

**Repo kembali private?** Clone lewat HTTPS tanpa key hanya berlaku selama repo `clau-agent` public. Bila private: sebelum langkah 3, buat deploy key read-only untuk user `clau-deploy` (§ 5, key di `/var/lib/clau-deploy/.ssh/clau_agents_deploy`, alias `github-agents`) dan jalankan setup dengan `sudo CLAU_REPO_URL=git@github-agents:deakasep/agent.git bash /tmp/vps1-setup.sh`.

## 1. Status (diperbarui 2026-10-22)

> **Server dimatikan owner 2026-10-22** (biaya). Tabel di bawah adalah riwayat server lama. Membuat lagi: § 0 (`vps1-setup.sh`), lalu hapus mesin lama di Tailscale dan deploy key lama di GitHub bila belum (kartu ClickUp TASK-065).

| Bagian | Status |
|---|---|
| 1–5. OS, hostname, user admin `dea` + SSH key | DATA FINAL — Ubuntu 24.04 LTS, kernel 6.8.0-146, 2 vCPU / 3.8 GB RAM / 79 GB |
| 6. Hardening (UFW, sshd, fail2ban, unattended-upgrades) | DATA FINAL — diverifikasi: UFW active (22/80/443), root & password login ditolak, fail2ban jail `sshd` active |
| 7a–7b. Node 22 + Nginx + swap 2 GB | DATA FINAL — 2026-10-07 |
| 7c. Tailscale | DATA FINAL — 2026-10-09: dipasang ulang (cek 2026-10-08 menemukan `tailscale` tidak terpasang dan `tailscaled` inactive), join ulang sebagai `clau-vps1`, `tailscaled` active. Entri lama offline diganti nama `clau-vps1-aja`. Users: Dea Karisna (Owner), Pak Indra (Admin, sejak 2026-10-07). 2026-10-13: entri `clau-vps1-aja` dihapus, key expiry `clau-vps1` dimatikan (dicek `clau-vps1-check`). NEXT ACTION: ACL setelah VPS 2 join |
| 8. Deploy frontend (akses via IP, HTTP) | DATA FINAL — 2026-10-07: service `clau-frontend` active, Nginx proxy ke 127.0.0.1:3000, halaman registry tampil di `http://<IP_VPS_1>` |
| 9. Auto-deploy dari repo (pull-based) | DATA FINAL — 2026-10-07: `clau-deploy.timer` aktif (5 menit), service frontend memakai `/srv/clau/current` |
| Cek kesehatan 2026-10-08 | DATA FINAL — `clau-frontend`, nginx, fail2ban, `clau-deploy.timer` active; `/team` HTTP 200; rilis live = `main` (`8948618`), commit tanpa perubahan frontend dilewati build; UFW 22/80/443; disk 11%, RAM tersedia 3,3 GB; 0 update keamanan tertunda |
| 10. Domain + Cloudflare + SSL | Ditunda — domain belum ada (owner, 2026-10-13). Selama itu VPS 1 tetap pratinjau tanpa login |
| 11. Backup config (tanpa `.env`) | DATA FINAL — 2026-10-13: dipasang owner (`vps1-harden.sh`), `sudo clau-vps1-check` = **0 gagal, 0 perlu dicek**: backup pertama `vps1-config-20261013T113858Z` (17 file config), lalu mingguan ke `/var/backups/clau/`. NEXT ACTION: salinan di luar server bersama Backblaze B2 (VPS 2) |
| 13. User khusus, jaringan web dikunci, cek & backup rutin | DATA FINAL — 2026-10-13: dipasang owner (`vps1-harden.sh`), `sudo clau-vps1-check` = **0 gagal, 0 perlu dicek**: frontend sebagai `clau-web` (exposure 1.3), deploy sebagai `clau-deploy` (rilis `013f587`), deploy key lama di `~dea` dihapus, UFW/SSH/fail2ban/Tailscale OK, disk 12%, RAM tersedia 2,7 GB |
| 15. Setup satu perintah untuk VPS baru / pengganti | DATA FINAL — 2026-10-18: `scripts/deploy/vps1-setup.sh` (§ 0), diuji di Ubuntu 24.04 baru (container systemd): 0 gagal di `clau-vps1-check` |
| 14. Gerbang deploy `release/vps1` (AI-BOUNDARY 1.3.0) | DATA FINAL — 2026-10-13: job CI `release-vps1` membuat branch, `vps1-harden.sh` dijalankan ulang; `clau-vps1-check` = 0 gagal, 0 perlu dicek ("deploy hanya dari release/vps1", rilis aktif `130af9b`) |
| 12. Pengerasan keamanan aplikasi (header, Nginx, sandbox systemd) | DATA FINAL — 2026-10-09: rilis `8acf7a4` live (CSP & `X-Frame-Options: DENY` ada, `X-Powered-By` hilang); Nginx `scripts/deploy/nginx/clau.conf` terpasang (`nginx -t` OK; `/` 200, POST 405, `/.env` 404); `clau-frontend.service` sandbox terpasang, `active`, `systemd-analyze security` = **1.4 OK**. Backup: `/etc/nginx/sites-available/clau.bak`, `/etc/systemd/system/clau-frontend.service.bak`. Proteksi `main` + Dependabot alerts: aktif (owner, 2026-10-09) |

## 2. Aturan

- Login hanya `ssh dea@<IP_VPS_1>` dengan SSH key. Root login dan password login **mati**.
- Paste **satu perintah per baris** saat ada `sudo` (baris berikutnya bisa terbaca sebagai password).
- Tetap di Ubuntu 24.04 LTS. **Jangan** `do-release-upgrade` tanpa rencana terpisah.
- VPS 1 **tidak** menyimpan API key AI atau database (keputusan #1, #6). Semua itu di VPS 2.
- Port publik hanya 22, 80, 443. App Next.js listen di `127.0.0.1:3000` dan hanya diakses lewat Nginx.

## 3. Bagian 1–6 — Akses & Hardening (sudah selesai)

```bash
# sebagai root (sekali, lalu root login dimatikan)
hostnamectl set-hostname clau-vps1
adduser dea && usermod -aG sudo dea
mkdir -p /home/dea/.ssh && cp /root/.ssh/authorized_keys /home/dea/.ssh/
chown -R dea:dea /home/dea/.ssh && chmod 700 /home/dea/.ssh && chmod 600 /home/dea/.ssh/authorized_keys

# sebagai dea
sudo apt update && sudo apt -y full-upgrade
sudo apt -y install ufw fail2ban unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades

sudo ufw default deny incoming && sudo ufw default allow outgoing
sudo ufw allow OpenSSH && sudo ufw allow 80/tcp && sudo ufw allow 443/tcp
sudo ufw enable

# 00- supaya menang dari 50-cloud-init.conf (sshd memakai nilai pertama yang ditemukan)
printf "PermitRootLogin no\nPasswordAuthentication no\nKbdInteractiveAuthentication no\n" | sudo tee /etc/ssh/sshd_config.d/00-clau.conf
sudo mkdir -p /run/sshd          # Ubuntu 24.04 (socket activation): wajib sebelum sshd -t
sudo sshd -t && sudo systemctl restart ssh

printf "[sshd]\nenabled = true\nbackend = systemd\nmaxretry = 5\nfindtime = 10m\nbantime = 1h\n" | sudo tee /etc/fail2ban/jail.local
sudo systemctl enable --now fail2ban
sudo reboot                      # memuat kernel baru
```

Verifikasi:

```bash
sudo ufw status verbose                       # active; 22, 80, 443 ALLOW IN
sudo sshd -T | grep -E "permitrootlogin|passwordauthentication|kbdinteractive"   # semua no
sudo fail2ban-client status sshd              # jail aktif
ssh root@<IP_VPS_1>                           # dari laptop: Permission denied (publickey)
```

## 4. Bagian 7 — Runtime

```bash
curl -fsSL https://deb.nodesource.com/setup_22.x -o /tmp/nodesource_setup.sh
sudo bash /tmp/nodesource_setup.sh
sudo apt -y install nodejs nginx
node -v                                       # v22.x
sudo systemctl is-active nginx                # active
```

Swap 2 GB (default 495 MB terlalu kecil untuk `next build` di RAM 3.8 GB):

```bash
sudo swapon --show                            # catat nama file swap lama bila ada
sudo fallocate -l 2G /swapfile2 && sudo chmod 600 /swapfile2
sudo mkswap /swapfile2 && sudo swapon /swapfile2
echo '/swapfile2 none swap sw 0 0' | sudo tee -a /etc/fstab
```

Tailscale (7c), tailnet milik Dea Karisna: `curl -fsSL https://tailscale.com/install.sh | sh`, lalu `sudo tailscale up --hostname=clau-vps1` dan login lewat link yang muncul. Di admin console: Disable key expiry untuk `clau-vps1`, undang Pak Indra sebagai Admin.

## 5. Bagian 8 — Deploy Frontend

Repo private → pakai **deploy key read-only** khusus repo ini (bukan key pribadi, bukan PAT). Frontend hanya membaca `agents/registry.json`, jadi submodule `core/` tidak perlu di-clone di VPS 1.

```bash
ssh-keygen -t ed25519 -f ~/.ssh/clau_agents_deploy -N "" -C "clau-vps1 deploy (read-only)"
cat ~/.ssh/clau_agents_deploy.pub
# GitHub → clau-agent → Settings → Deploy keys → Add deploy key
#   Title: clau-vps1 ; Allow write access: JANGAN dicentang

printf "Host github-agents\n  HostName github.com\n  User git\n  IdentityFile ~/.ssh/clau_agents_deploy\n  IdentitiesOnly yes\n" >> ~/.ssh/config
chmod 600 ~/.ssh/config
ssh -T github-agents                          # "successfully authenticated"

sudo mkdir -p /srv/clau && sudo chown dea:dea /srv/clau
git clone git@github-agents:deakasep/agent.git /srv/clau/clau-ai-agents
cd /srv/clau/clau-ai-agents/frontend
npm ci && npm run build
```

Service systemd (`/etc/systemd/system/clau-frontend.service`):

```ini
[Unit]
Description=CLAU AI frontend (Next.js)
After=network.target

[Service]
User=dea
WorkingDirectory=/srv/clau/clau-ai-agents/frontend
Environment=NODE_ENV=production
ExecStart=/usr/bin/node node_modules/next/dist/bin/next start -H 127.0.0.1 -p 3000
Restart=on-failure
NoNewPrivileges=true
ProtectSystem=full
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now clau-frontend
curl -sI http://127.0.0.1:3000 | head -1      # HTTP/1.1 200 OK
```

Nginx (`/etc/nginx/sites-available/clau`), `server_name _` sampai domain ditentukan. Versi yang dikeraskan (rate limit, GET/HEAD saja, batas body & timeout) ada di `scripts/deploy/nginx/clau.conf` — pasang lewat [§ 7](#7-bagian-12--pengerasan-keamanan-2026-10-09):

```nginx
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;
    server_tokens off;

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

```bash
sudo rm /etc/nginx/sites-enabled/default
sudo ln -s /etc/nginx/sites-available/clau /etc/nginx/sites-enabled/clau
sudo nginx -t && sudo systemctl reload nginx
# browser: http://<IP_VPS_1> → halaman registry agent
```

Update versi baru:

```bash
cd /srv/clau/clau-ai-agents && git pull
cd frontend && npm ci && npm run build && sudo systemctl restart clau-frontend
```

## 6. Bagian 9 — Auto-Deploy dari Repo

Setiap 5 menit VPS 1 mengecek branch `release/vps1` (sejak 2026-10-13; sebelumnya `main`). Branch ini dimajukan job CI `release-vps1` hanya ke commit `main` yang semua job CI-nya hijau. Bila ada perubahan di `frontend/`, `agents/registry.json`, `agents/personas/`, atau `agents/evals/cases/` (jumlah kasus uji tampil di UI), server build rilis baru **di samping** rilis yang sedang jalan, lalu pindah ke rilis baru. Commit yang hanya mengubah dokumen tidak memicu build.

| Sifat | Keterangan |
|---|---|
| Pull-based | GitHub tidak punya akses ke server (tidak ada SSH key/secret server di GitHub). Server menarik kode dengan deploy key read-only |
| Build gagal | Rilis lama tetap jalan; commit itu tidak dicoba ulang tiap 5 menit sampai ada commit baru atau `--force` |
| Health check gagal | Otomatis rollback ke rilis sebelumnya |
| Riwayat | 3 rilis terakhir disimpan di `/srv/clau/releases/`; `/srv/clau/current` menunjuk rilis aktif |

Pasang (sekali):

```bash
cd /srv/clau/clau-ai-agents && git pull --ff-only

# izinkan dea me-restart service frontend saja, tanpa password
echo 'dea ALL=(root) NOPASSWD: /usr/bin/systemctl restart clau-frontend' | sudo tee /etc/sudoers.d/clau-deploy
sudo chmod 440 /etc/sudoers.d/clau-deploy && sudo visudo -c

# rilis pertama (membuat /srv/clau/current)
scripts/deploy/vps1-deploy.sh --force

# service frontend pindah ke rilis aktif
sudo sed -i 's#^WorkingDirectory=.*#WorkingDirectory=/srv/clau/current/frontend#' /etc/systemd/system/clau-frontend.service
sudo systemctl daemon-reload && sudo systemctl restart clau-frontend

# timer
sudo cp scripts/deploy/systemd/clau-deploy.service scripts/deploy/systemd/clau-deploy.timer /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now clau-deploy.timer
```

Operasional:

```bash
systemctl list-timers clau-deploy.timer          # jadwal cek berikutnya
journalctl -u clau-deploy -n 30 --no-pager       # log deploy
/srv/clau/clau-ai-agents/scripts/deploy/vps1-deploy.sh --force   # deploy manual sekarang
ls -l /srv/clau/current                          # rilis aktif
```

Rollback manual ke rilis sebelumnya:

```bash
ls -1t /srv/clau/releases/                       # pilih folder rilis
ln -sfn /srv/clau/releases/<folder> /srv/clau/current && sudo systemctl restart clau-frontend
```

## 7. Bagian 12 — Pengerasan Keamanan (2026-10-09)

Ringkasan ancaman dan alasan tiap pengaturan: [`../security.md`](../security.md). Header keamanan (CSP, anti-clickjacking, dll.) sudah ikut auto-deploy. Dua langkah di bawah dipasang **sekali, manual**, satu perintah per baris.

**a. Nginx** (rate limit, GET/HEAD saja, body 16 KB, timeout pendek):

```bash
cd /srv/clau/clau-ai-agents && git pull --ff-only
sudo cp /etc/nginx/sites-available/clau /etc/nginx/sites-available/clau.bak
sudo cp scripts/deploy/nginx/clau.conf /etc/nginx/sites-available/clau
sudo nginx -t
sudo systemctl reload nginx
curl -sI http://127.0.0.1/ | head -1                      # HTTP/1.1 200 OK
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1/   # 405
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1/.env       # 404
```

Bila `nginx -t` gagal: `sudo cp /etc/nginx/sites-available/clau.bak /etc/nginx/sites-available/clau` lalu `sudo systemctl reload nginx`.

**b. Sandbox systemd untuk frontend** (sistem read-only, `/home` tidak terbaca, tanpa hak tambahan):

```bash
sudo cp /etc/systemd/system/clau-frontend.service /etc/systemd/system/clau-frontend.service.bak
sudo cp scripts/deploy/systemd/clau-frontend.service /etc/systemd/system/clau-frontend.service
sudo systemctl daemon-reload
sudo systemctl restart clau-frontend
systemctl is-active clau-frontend                          # active
curl -sI http://127.0.0.1:3000 | head -1                   # HTTP/1.1 200 OK
systemd-analyze security clau-frontend | tail -1           # skor exposure (makin kecil makin aman)
```

Bila tidak `active` atau curl gagal: `journalctl -u clau-frontend -n 30 --no-pager` (kirim ke agent), lalu kembalikan dengan `sudo cp /etc/systemd/system/clau-frontend.service.bak /etc/systemd/system/clau-frontend.service`, `sudo systemctl daemon-reload`, `sudo systemctl restart clau-frontend`.

**c. GitHub** (owner): Settings → Branches → proteksi `main` (wajib PR, CI hijau termasuk job `audit`). Settings → Code security → aktifkan Dependabot alerts & security updates.

## 8. Bagian 13 — User Khusus, Cek & Backup Rutin (2026-10-13)

Tanpa domain, ini langkah terakhir agar VPS 1 maksimal untuk perannya sekarang (pratinjau tanpa login/data).

| Sebelum | Sesudah |
|---|---|
| Frontend dan deploy jalan sebagai `dea` (admin, punya sudo) | Frontend = `clau-web` (tanpa login/sudo, hanya membaca); deploy = `clau-deploy` (pemilik `/srv/clau` + deploy key, sudo hanya restart frontend) |
| Proses web bisa menulis folder rilis & menghubungi internet | Semua read-only; jaringan hanya localhost + Tailscale |
| Cek kesehatan manual, perintah satu per satu | `sudo clau-vps1-check`: satu daftar OK / PERLU DICEK / GAGAL |
| Backup config belum ada | Mingguan (Minggu 02:00), tanpa `.env`/private key, 8 terakhir |
| Update kernel menunggu reboot manual | Reboot otomatis 03:30 WITA bila update keamanan memerlukannya (pratinjau mati ±1 menit) |

**Pasang** (sekali; ulangi bila file di `scripts/deploy/` berubah). Login `ssh dea@<IP_VPS_1>`, lalu satu perintah per baris:

```bash
sudo journalctl -u clau-deploy -n 3 --no-pager      # pastikan commit ini sudah ter-pull (≤ 5 menit setelah merge)
sudo bash /srv/clau/clau-ai-agents/scripts/deploy/vps1-harden.sh
```

Script berhenti dan **mengembalikan semuanya otomatis** bila satu langkah gagal (frontend tetap hidup sebagai `dea`); kirim outputnya ke agent. Hasil akhir = daftar `clau-vps1-check`. Yang wajib OK: Layanan, Aplikasi, Deploy, Keamanan server.

**Gerbang deploy (2026-10-13, AI-BOUNDARY 1.3.0).** Unit `clau-deploy.service` menetapkan `CLAU_BRANCH=release/vps1`. Setelah PR gerbang di-merge dan job CI `release-vps1` hijau sekali (branch dibuat otomatis), jalankan ulang perintah pasang di atas. Script berhenti dengan pesan jelas (dan mengembalikan semuanya) bila `release/vps1` belum ada. Cek: baris "deploy hanya dari release/vps1" = OK. Bila `main` lebih baru dari rilis, `clau-vps1-check` menampilkan "belum lolos CI" (PERLU DICEK, normal beberapa menit setelah merge; bila lama, CI `main` merah).

**Rutin** (mis. tiap Senin, atau setelah ada masalah):

```bash
sudo clau-vps1-check                                # screenshot hasilnya bila ada GAGAL
```

Sesudah tahap ini, `dea` tidak bisa membaca `/srv/clau` tanpa sudo (disengaja). Perintah operasional jadi:

```bash
sudo journalctl -u clau-deploy -n 30 --no-pager     # log deploy
sudo systemctl start clau-deploy                     # deploy sekarang (tanpa menunggu 5 menit)
sudo -u clau-deploy /srv/clau/clau-ai-agents/scripts/deploy/vps1-deploy.sh --force   # paksa build ulang
sudo ls -1t /var/backups/clau/                       # backup config
```

Rollback manual ke rilis sebelumnya: `sudo -u clau-deploy ln -sfn /srv/clau/releases/<folder> /srv/clau/current` lalu `sudo systemctl restart clau-frontend`. Kembali ke keadaan sebelum § 8: unit lama tersimpan di `/var/backups/clau/pre-harden-<waktu>/`.

**Tailscale (owner, admin console, ±5 menit):** hapus entri lama `clau-vps1-aja`; **Disable key expiry** untuk `clau-vps1` (tanpa ini VPS 1 terputus dari tailnet saat key habis). ACL dibuat saat VPS 2 bergabung.

## 9. RISK

- Selama belum ada domain + SSL, akses masih **HTTP via IP**. Aman untuk scaffold saat ini (tidak ada login/data), tetapi **jangan** menambahkan login, form, atau data client sebelum Bagian 9 (HTTPS) selesai.
- `vps1-harden.sh` dijalankan root dari folder repo milik `clau-deploy`. Isinya = `main` di GitHub (ditarik deploy key), jadi kepercayaan sama dengan kode yang tayang; jalankan hanya setelah PR terkait di-merge.
- Gerbang deploy (AI-BOUNDARY 1.3.0): VPS 1 hanya menayangkan `release/vps1`, yang dimajukan job CI `release-vps1` ke commit `main` setelah `backend`, `frontend`, `audit`, `docker` hijau. Commit merah tidak tayang; tetap tinggal di `main` sampai diperbaiki.
- Merge ke `main` tampil di VPS 1 ±5 menit **setelah CI `main` hijau** (±3 menit CI + ≤5 menit timer). `main` tetap wajib lewat PR dengan CI hijau (`core/AI-BOUNDARY.md` § Disiplin Push, dijaga `main-guard`).
