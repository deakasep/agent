#!/usr/bin/env bash
# Setup VPS 1 (dashboard pratinjau) dari nol dalam satu perintah (docs/deploy/vps-1-setup.md § 0).
# Untuk VPS baru atau pengganti; aman diulang di VPS yang sudah jalan.
#
#   sudo bash vps1-setup.sh
#
# Prasyarat (± 5 menit, panduan § 0): Ubuntu 24.04, user admin (mis. dea) dengan sudo + SSH key,
# Tailscale tersambung (`sudo tailscale up --hostname=clau-vps1`). Repo clau-agent public: tidak butuh deploy key.
#
# Yang dipasang (sama dengan VPS 1 sekarang, § 3–8):
#   1. Update sistem, Node.js 22, Nginx, firewall (hanya 22/80/443), SSH tanpa root/password, fail2ban
#   2. Update keamanan otomatis + reboot 03:30 WITA bila perlu, batas log, swap 2 GB
#   3. User clau-web (menjalankan frontend, hanya membaca) dan clau-deploy (pemilik /srv/clau, sudo hanya restart)
#   4. Repo di /srv/clau/clau-ai-agents, rilis pertama dari release/vps1 (commit main yang CI-nya hijau)
#   5. Unit systemd dari repo, Nginx yang dikeraskan, deploy otomatis tiap 5 menit, cek & backup config mingguan
# VPS 1 tidak menyimpan data atau secret: tidak ada yang perlu dipulihkan.
set -euo pipefail

ROOT=/srv/clau
REPO="$ROOT/clau-ai-agents"
REPO_URL="${CLAU_REPO_URL:-https://github.com/deakasep/agent.git}"
DEPLOY_HOME=/var/lib/clau-deploy
ADMIN="${SUDO_USER:-}"

log() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
die() { printf '\033[31mGAGAL: %s\033[0m\n' "$*" >&2; exit 1; }
as_deploy() { runuser -u clau-deploy -- env HOME="$DEPLOY_HOME" "$@"; }

[ "$(id -u)" -eq 0 ] || die "jalankan dengan sudo"
cd /  # user clau-deploy tidak bisa membaca folder home admin; git butuh folder kerja yang terbaca
[ -n "$ADMIN" ] && [ "$ADMIN" != root ] || die "jalankan dari user admin (mis. dea) dengan sudo, bukan login root"
. /etc/os-release
[ "$ID" = ubuntu ] && [ "$VERSION_ID" = "24.04" ] || die "butuh Ubuntu 24.04 (ini $PRETTY_NAME)"
admin_home=$(getent passwd "$ADMIN" | cut -d: -f6)
[ -s "$admin_home/.ssh/authorized_keys" ] || die "$ADMIN belum punya SSH key ($admin_home/.ssh/authorized_keys); login password akan dimatikan dan kamu terkunci"

log "1/8 Update sistem, Node.js 22, Nginx"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get -y -q full-upgrade
apt-get -y -q install ufw fail2ban unattended-upgrades ca-certificates curl git gnupg nginx python3 >/dev/null
if ! node -v 2>/dev/null | grep -q '^v22\.'; then
  # Repo apt resmi NodeSource (kunci ditandatangani), bukan script yang dijalankan langsung dari internet.
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor --yes -o /etc/apt/keyrings/nodesource.gpg
  echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" > /etc/apt/sources.list.d/nodesource.list
  apt-get update -q
  apt-get -y -q install nodejs >/dev/null
fi
echo "node $(node -v), npm $(npm -v)"
hostnamectl set-hostname clau-vps1 2>/dev/null || echo "(nama host tidak diubah; tidak masalah)"

log "2/8 Firewall (22, 80, 443), SSH tanpa root/password, fail2ban"
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw allow OpenSSH >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null
# 00- supaya menang dari 50-cloud-init.conf (sshd memakai nilai pertama yang ditemukan).
printf 'PermitRootLogin no\nPasswordAuthentication no\nKbdInteractiveAuthentication no\n' > /etc/ssh/sshd_config.d/00-clau.conf
mkdir -p /run/sshd
sshd -t
systemctl restart ssh
printf '[sshd]\nenabled = true\nbackend = systemd\nmaxretry = 5\nfindtime = 10m\nbantime = 1h\n' > /etc/fail2ban/jail.local
systemctl enable --now fail2ban >/dev/null
systemctl restart fail2ban

log "3/8 Update keamanan otomatis, batas log, swap"
printf 'APT::Periodic::Update-Package-Lists "1";\nAPT::Periodic::Unattended-Upgrade "1";\n' > /etc/apt/apt.conf.d/20auto-upgrades
# Jam lokal server yang sama dengan 03:30 WITA (server biasanya UTC → 19:30).
reboot_at=$(date -d 'TZ="Asia/Makassar" 03:30' +%H:%M)
cat > /etc/apt/apt.conf.d/52clau-auto-reboot <<EOF
// Dipasang vps1-setup.sh: kernel/libc baru aktif tanpa menunggu reboot manual (pratinjau mati ±1 menit).
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "$reboot_at";
EOF
mkdir -p /etc/systemd/journald.conf.d
printf '[Journal]\nSystemMaxUse=300M\n' > /etc/systemd/journald.conf.d/clau.conf
systemctl restart systemd-journald
# `next build` butuh RAM: swap 2 GB bila belum ada swap sama sekali.
if ! swapon --show | grep -q .; then
  if fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile; then
    grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  else
    echo "(swap tidak bisa dibuat; build tetap dicoba)"
  fi
fi

log "4/8 Tailscale"
command -v tailscale >/dev/null || die "Tailscale belum terpasang (panduan § 0 langkah 2), lalu ulangi script ini"
tailscale status >/dev/null 2>&1 || die "Tailscale belum login: sudo tailscale up --hostname=clau-vps1 (buka link yang muncul), lalu ulangi"
echo "terhubung sebagai $(tailscale status --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["HostName"])')"

log "5/8 User clau-web & clau-deploy, repo di commit release/vps1"
getent group clau-web >/dev/null || groupadd --system clau-web
id clau-web >/dev/null 2>&1 || useradd --system --gid clau-web --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin clau-web
id clau-deploy >/dev/null 2>&1 || useradd --system --user-group --create-home --home-dir "$DEPLOY_HOME" --shell /usr/sbin/nologin clau-deploy
chmod 700 "$DEPLOY_HOME"
install -d -m 755 "$ROOT"
chown clau-deploy:clau-web "$ROOT"
if [ ! -d "$REPO/.git" ]; then
  # Repo public: clone lewat HTTPS tanpa key. Bila repo kembali private, tambahkan deploy key (panduan § 0).
  as_deploy git ls-remote --exit-code "$REPO_URL" refs/heads/release/vps1 >/dev/null \
    || die "tidak bisa membaca $REPO_URL (repo private? lihat panduan § 0 bagian deploy key)"
  as_deploy git clone --quiet --no-checkout "$REPO_URL" "$REPO"
fi
# Repo milik clau-deploy, hanya bisa dibaca clau-web (setgid: file baru ikut grup clau-web).
chown -R clau-deploy:clau-web "$ROOT"
chmod -R u+rwX,g+rX,g-w,o-rwx "$ROOT"
find "$ROOT" -type d -exec chmod g+s {} +
as_deploy git -C "$REPO" fetch --quiet origin release/vps1 \
  || die "branch release/vps1 belum ada / tidak terbaca (tunggu job CI release-vps1 di main hijau)"
as_deploy git -C "$REPO" checkout --quiet --detach FETCH_HEAD
echo "commit: $(as_deploy git -C "$REPO" rev-parse --short HEAD)"
SRC="$REPO/scripts/deploy"

log "6/8 sudo terbatas, unit systemd, Nginx, alat cek & backup"
tmp=$(mktemp)
echo 'clau-deploy ALL=(root) NOPASSWD: /usr/bin/systemctl restart clau-frontend' > "$tmp"
visudo -cf "$tmp" >/dev/null
install -m 440 -o root -g root "$tmp" /etc/sudoers.d/clau-deploy
rm -f "$tmp"
for u in clau-frontend.service clau-deploy.service clau-deploy.timer clau-config-backup.service clau-config-backup.timer; do
  install -m 644 -o root -g root "$SRC/systemd/$u" "/etc/systemd/system/$u"
done
# Salinan milik root: script yang dijalankan root tidak boleh bisa diubah user clau-deploy.
install -m 755 -o root -g root "$SRC/vps1-check.sh" /usr/local/sbin/clau-vps1-check
install -m 755 -o root -g root "$SRC/vps1-backup-config.sh" /usr/local/sbin/clau-backup-config
systemctl daemon-reload
systemctl enable clau-frontend >/dev/null
nginx_old=""
[ -f /etc/nginx/sites-available/clau ] && nginx_old=$(mktemp) && cp -a /etc/nginx/sites-available/clau "$nginx_old"
if [ -e /proc/net/if_inet6 ]; then
  install -m 644 -o root -g root "$SRC/nginx/clau.conf" /etc/nginx/sites-available/clau
else
  # Sebagian provider mematikan IPv6: Nginx menolak `listen [::]`. clau-vps1-check akan menandai "beda dengan repo".
  sed '/listen \[::\]/d' "$SRC/nginx/clau.conf" > /etc/nginx/sites-available/clau
  chmod 644 /etc/nginx/sites-available/clau
  echo "(server tanpa IPv6: Nginx hanya IPv4)"
fi
ln -sfn /etc/nginx/sites-available/clau /etc/nginx/sites-enabled/clau
rm -f /etc/nginx/sites-enabled/default
if ! nginx -t 2>/dev/null; then
  nginx -t || true
  if [ -n "$nginx_old" ]; then
    cp -a "$nginx_old" /etc/nginx/sites-available/clau
    die "konfigurasi Nginx baru tidak valid (konfigurasi lama dikembalikan)"
  fi
  rm -f /etc/nginx/sites-enabled/clau
  die "konfigurasi Nginx tidak valid (lihat pesan nginx di atas)"
fi
[ -n "$nginx_old" ] && rm -f "$nginx_old"
systemctl enable nginx >/dev/null
systemctl reload-or-restart nginx

log "7/8 Rilis frontend (build ±5–10 menit pertama kali)"
# Rilis yang pernah gagal dicoba lagi saat setup dijalankan ulang.
rm -f "$ROOT/.failed-sha"
systemctl start clau-deploy.service || die "deploy gagal (sudo journalctl -u clau-deploy -n 50 --no-pager)"
systemctl restart clau-frontend
for _ in $(seq 1 30); do curl -fs -o /dev/null http://127.0.0.1:3000 && break; sleep 1; done
curl -fs -o /dev/null http://127.0.0.1:3000 || die "frontend tidak sehat (sudo journalctl -u clau-frontend -n 30 --no-pager)"
pid=$(systemctl show -p MainPID --value clau-frontend)
[ "$(ps -o user= -p "$pid" | tr -d ' ')" = clau-web ] || die "frontend tidak jalan sebagai clau-web"
echo "frontend sehat sebagai clau-web, rilis $(cut -c1-7 "$ROOT/current/.sha")"
systemctl enable --now clau-deploy.timer clau-config-backup.timer >/dev/null

log "8/8 Backup config pertama & cek"
/usr/local/sbin/clau-backup-config
printf '\n\033[32mSelesai.\033[0m Dashboard: http://<IP_VPS_1> (atau lewat Tailscale). Hasil cek:\n'
/usr/local/sbin/clau-vps1-check || true
