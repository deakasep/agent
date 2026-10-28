"""Paket deploy VPS 1 (scripts/deploy/, docs/deploy/vps-1-setup.md § 8).

Script ini dijalankan root di server, jadi kesalahan kecil (sintaks, opsi systemd yang mematikan sudo,
file yang dipasang tapi tidak dicek) baru ketahuan saat owner menjalankannya. Test ini menjaganya di CI.
"""

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "scripts" / "deploy"
UNITS = DEPLOY / "systemd"


def unit(name: str) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for line in (UNITS / name).read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values.setdefault(key.strip(), []).append(value.strip())
    return values


@pytest.mark.parametrize("script", sorted((ROOT / "scripts").rglob("*.sh")), ids=lambda p: str(p.relative_to(ROOT)))
def test_shell_scripts_parse(script):
    subprocess.run(["bash", "-n", str(script)], check=True)


def test_frontend_runs_as_read_only_user_without_internet():
    u = unit("clau-frontend.service")
    assert u["User"] == ["clau-web"] and u["Group"] == ["clau-web"]
    assert u["ProtectSystem"] == ["strict"]
    assert "ReadWritePaths" not in u, "frontend tidak menulis apa pun (tanpa ISR/next/image)"
    assert u["IPAddressDeny"] == ["any"]
    assert u["NoNewPrivileges"] == ["true"]


def test_deploy_service_keeps_sudo_working():
    # sudo gagal di bawah NoNewPrivileges; opsi ini memasang seccomp/NNP secara tidak langsung.
    u = unit("clau-deploy.service")
    assert u["User"] == ["clau-deploy"]
    for option in ("NoNewPrivileges", "PrivateDevices", "ProtectKernelModules", "SystemCallFilter", "RestrictSUIDSGID"):
        assert option not in u, f"{option} membuat sudo restart frontend gagal"
    assert u["ExecStart"] == ["/srv/clau/clau-ai-agents/scripts/deploy/vps1-deploy.sh"]


def test_sudo_rule_matches_deploy_restart_and_check():
    harden = (DEPLOY / "vps1-harden.sh").read_text()
    check = (DEPLOY / "vps1-check.sh").read_text()
    deploy = (DEPLOY / "vps1-deploy.sh").read_text()
    rule = re.search(r"echo '(clau-deploy ALL=\(root\) NOPASSWD: (\S+ \S+ \S+))'", harden)
    assert rule, "aturan sudoers tidak ditemukan di vps1-harden.sh"
    assert f"'^{rule.group(1)}$'" in check, "clau-vps1-check harus mengecek aturan sudoers yang sama persis"
    assert f"sudo -n {rule.group(2)}" in deploy


def test_check_covers_every_installed_file():
    harden = (DEPLOY / "vps1-harden.sh").read_text()
    check = (DEPLOY / "vps1-check.sh").read_text()
    units = re.search(r"for u in ([^;]+); do\n  install -m 644", harden).group(1).split()
    for name in units:
        assert (UNITS / name).is_file()
        assert f"systemd/{name}:/etc/systemd/system/{name}" in check, f"{name} dipasang tapi tidak dicek"
    for src, dst in re.findall(r'install -m 755 -o root -g root "\$SRC/(\S+)" (\S+)', harden):
        assert f"{src}:{dst}" in check, f"{dst} dipasang tapi tidak dicek"
    assert "nginx/clau.conf:/etc/nginx/sites-available/clau" in check


def test_backup_never_includes_secrets():
    backup = (DEPLOY / "vps1-backup-config.sh").read_text()
    paths = re.search(r"paths=\(\n(.*?)\n\)", backup, re.S).group(1).split()
    for p in paths:
        assert not re.search(r"\.env|_deploy$|id_|\.key$|ssh_host", p), p


def test_vps1_only_deploys_ci_green_release_branch():
    # AI-BOUNDARY 1.3.0: VPS 1 menayangkan release/vps1, yang hanya dimajukan job CI setelah semua job hijau.
    assert "CLAU_BRANCH=release/vps1" in unit("clau-deploy.service")["Environment"]
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    job = ci.split("\n  release-vps1:\n", 1)[1]
    needs = set(re.search(r"needs: \[([^\]]+)\]", job).group(1).replace(" ", "").split(","))
    jobs = set(re.findall(r"^  ([a-z0-9-]+):\n", ci.split("\njobs:\n", 1)[1], re.M)) - {"release-vps1"}
    assert needs == jobs, "release-vps1 harus menunggu semua job CI"
    assert "github.ref == 'refs/heads/main'" in job
    deploy = (DEPLOY / "vps1-deploy.sh").read_text()
    assert 'fetch --quiet origin "$BRANCH"' in deploy and "FETCH_HEAD" in deploy and not re.search(r"git .*\bpull\b", deploy)



def test_vps1_setup_installs_same_as_harden_and_everything_is_checked():
    # vps1-setup.sh (VPS baru/pengganti, § 0) harus menghasilkan server yang sama dengan VPS 1 sekarang (§ 8).
    setup = (DEPLOY / "vps1-setup.sh").read_text()
    harden = (DEPLOY / "vps1-harden.sh").read_text()
    check = (DEPLOY / "vps1-check.sh").read_text()
    pattern = r"for u in ([^;]+); do\n  install -m 644"
    assert re.search(pattern, setup).group(1).split() == re.search(pattern, harden).group(1).split()
    tools = r'install -m 755 -o root -g root "\$SRC/(\S+)" (\S+)'
    assert re.findall(tools, setup) == re.findall(tools, harden)
    rule = re.search(r"echo '(clau-deploy ALL=\(root\) NOPASSWD: [^']+)'", setup).group(1)
    assert f"'^{rule}$'" in check
    assert "nginx/clau.conf" in setup and "/etc/nginx/sites-available/clau" in setup
    for timer in ("clau-deploy.timer", "clau-config-backup.timer"):
        assert timer in setup and timer in check


def test_vps1_setup_opens_only_checked_ports_and_never_locks_admin_out():
    setup = (DEPLOY / "vps1-setup.sh").read_text()
    allowed = set(re.findall(r"^ufw allow (\S+)", setup, re.M))
    assert allowed == {"OpenSSH", "80/tcp", "443/tcp"}, "clau-vps1-check hanya menerima 22, 80, 443"
    # Login password dimatikan: script harus berhenti dulu bila admin belum punya SSH key.
    assert setup.index("authorized_keys") < setup.index("PasswordAuthentication no")
    assert "PermitRootLogin no" in setup


def test_vps1_setup_deploys_only_ci_green_release_and_reads_repo_without_secrets():
    setup = (DEPLOY / "vps1-setup.sh").read_text()
    assert "fetch --quiet origin release/vps1" in setup and "FETCH_HEAD" in setup
    assert "systemctl start clau-deploy.service" in setup, "rilis pertama lewat unit yang sama dengan timer"
    assert re.search(r'REPO_URL="\$\{CLAU_REPO_URL:-https://github\.com/deakasep/agent\.git\}"', setup)
    assert not re.search(r"\| *(ba)?sh\b", setup), "tidak menjalankan script langsung dari internet"
    # Script yang dijalankan root disalin milik root, bukan dijalankan dari repo milik clau-deploy.
    assert "/usr/local/sbin/clau-vps1-check" in setup

# --- VPS 2 (docs/deploy/vps-2-setup.md) ----------------------------------------------------------------


def test_vps2_setup_installs_every_checked_file():
    setup = (DEPLOY / "vps2-setup.sh").read_text()
    units = re.search(r"for u in ([^;]+); do\n  install -m 644", setup).group(1).split()
    for name in units:
        assert (UNITS / name).is_file(), name
    for src, dst in re.findall(r'install -m 755 -o root -g root "\$SRC/(\S+)" (\S+)', setup):
        assert (DEPLOY / src).is_file(), src
    check = (DEPLOY / "vps2-check.sh").read_text()
    for timer in (u for u in units if u.endswith(".timer")):
        assert timer in check, f"{timer} dipasang tapi tidak dicek"


def test_vps2_deploys_only_ci_green_release_branch_and_rolls_back():
    deploy = (DEPLOY / "vps2-deploy.sh").read_text()
    assert "CLAU_BRANCH=release/vps1" in unit("clau2-deploy.service")["Environment"]
    assert unit("clau2-deploy.service")["ExecStart"] == ["/usr/local/sbin/clau-vps2-deploy"], "jalankan salinan milik root, bukan file repo"
    assert 'fetch --quiet origin "$BRANCH"' in deploy and "FETCH_HEAD" in deploy and not re.search(r"git .*\bpull\b", deploy)
    # Migrasi baru: backup dulu; gagal: skema diturunkan lalu image & commit lama dipakai lagi.
    assert "clau-vps2-backup" in deploy.split('log "build')[0]
    assert "alembic downgrade" in deploy and ':prev" "$img:local"' in deploy


def test_vps2_app_is_never_public():
    setup = (DEPLOY / "vps2-setup.sh").read_text()
    assert "ufw default deny incoming" in setup and "ufw allow in on tailscale0" in setup
    assert "tailscale funnel" not in setup.replace("tailscale funnel status", ""), "Funnel membuka aplikasi ke internet"
    assert "--https=443 http://127.0.0.1:3000" in setup
    compose = (ROOT / "docker-compose.yml").read_text()
    ports = re.findall(r'ports: \["([^"]+)"\]', compose)
    assert ports and all(p.startswith("127.0.0.1:") for p in ports), ports
    assert 'CLAU_ALLOWED_ORIGINS "https://$dns"' in setup and 'CLAU_PUBLIC_ORIGIN "https://$dns"' in setup


def test_vps2_secrets_stay_root_only():
    setup = (DEPLOY / "vps2-setup.sh").read_text()
    assert 'chmod 600 "$REPO/.env"' in setup and 'chmod 600 "$KEY"' in setup
    check = (DEPLOY / "vps2-check.sh").read_text()
    assert "CLAU_BACKUP_PASSPHRASE=" not in check.replace("simpan CLAU_BACKUP_PASSPHRASE", ""), "cek tidak boleh menampilkan secret"


def test_frontend_healthcheck_does_not_follow_redirects():
    """Di balik HTTPS (CLAU_PUBLIC_ORIGIN) halaman yang dijaga mengarah ke alamat publik yang tidak terjangkau dari
    dalam container: health check harus memakai /login (200) tanpa mengikuti redirect (insiden VPS 2, 2026-10-15)."""
    dockerfile = (ROOT / "frontend" / "Dockerfile").read_text()
    check = re.search(r"HEALTHCHECK .*?\n(.*?)\n", dockerfile, re.S).group(1)
    assert "127.0.0.1:3000/login" in check and "redirect: 'manual'" in check and "status === 200" in check


def test_vps2_check_ignores_tailscale_and_loopback_listeners():
    """`ss` menulis alamat dengan zona (100.x%tailscale0, 127.0.0.53%lo): bukan port publik (alarm palsu 2026-10-15)."""
    check = (DEPLOY / "vps2-check.sh").read_text()
    func = re.search(r"^public_listeners\(\) \{.*?^\}", check, re.S | re.M).group(0)
    sample = "\n".join(f"LISTEN 0 4096 {addr} 0.0.0.0:*" for addr in (
        "100.64.0.10%tailscale0:62458", "127.0.0.53%lo:53", "127.0.0.54:53", "127.0.0.1:3000", "127.0.0.1:8000",
        "[fd7a:115c:a1e0::b338:2a47]%tailscale0:443", "0.0.0.0:22", "[::]:22", "[::1]:631",
        "0.0.0.0:5432", "203.0.113.10:8080", "[::]:3000",
    ))
    out = subprocess.run(["bash", "-c", f"{func}\npublic_listeners"], input=sample, capture_output=True, text=True, check=True).stdout.split()
    assert out == ["0.0.0.0:5432", "203.0.113.10:8080", "[::]:3000"]


@pytest.mark.parametrize(
    ("ssh_connection", "who", "expect"),
    [
        (None, "dea pts/1 2026-10-15 10:23 (100.64.0.20)", "lanjut"),  # sudo membuang SSH_CONNECTION (insiden 2026-10-15)
        (None, "dea pts/0 2026-10-15 09:55 (198.51.100.7)", "ditolak"),
        ("100.64.0.20 51000 100.64.0.10 22", "", "lanjut"),
        ("198.51.100.7 51000 203.0.113.10 22", "", "ditolak"),
        (None, "", "lanjut"),
    ],
)
def test_vps2_lock_ssh_detects_session_origin_under_set_u(ssh_connection, who, expect):
    """--lock-ssh dijalankan lewat sudo (SSH_CONNECTION kosong) dengan `set -u`: tidak boleh berhenti, dan sesi dari
    IP publik tetap ditolak."""
    setup = (DEPLOY / "vps2-setup.sh").read_text()
    block = re.search(r'^  remote="\$\{SSH_CONNECTION.*?^  esac$', setup, re.S | re.M).group(0)
    script = f"""set -euo pipefail
die() {{ echo ditolak; exit 0; }}
who() {{ printf '%s\\n' "$WHO_LINE"; }}
tailscale() {{ echo 100.64.0.10; }}
ADMIN=dea
{block}
echo lanjut
"""
    env = {"PATH": "/usr/bin:/bin", "WHO_LINE": who}
    if ssh_connection:
        env["SSH_CONNECTION"] = ssh_connection
    out = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().splitlines()[-1] == expect


# --- Backup & pemulihan VPS 2 (docs/deploy/vps-2-setup.md § I & § 5, keputusan owner 2026-10-15) ---------------


def test_vps2_backup_runs_every_six_hours_and_copies_offsite():
    timer = unit("clau2-backup.timer")
    assert timer["OnCalendar"] == ["*-*-* 02,08,14,20:00:00 Asia/Makassar"]
    assert timer["Persistent"] == ["true"], "backup yang terlewat (server mati) dijalankan saat server hidup lagi"
    backup = (DEPLOY / "vps2-backup.sh").read_text()
    assert "clau-vps2-offsite push" in backup and "/etc/clau/offsite.env" in backup
    check = (DEPLOY / "vps2-check.sh").read_text()
    assert '[ "$age" -le 13 ]' in check and '[ "$sent_age" -le 13 ]' in check, "cek harus tahu jadwal 6 jam"
    setup = (DEPLOY / "vps2-setup.sh").read_text()
    assert re.search(r"apt-get .* install .*\brclone\b", setup)
    for tool in ("offsite", "restore"):
        assert f'"$SRC/vps2-{tool}.sh" /usr/local/sbin/clau-vps2-{tool}' in setup


def test_vps2_purges_old_sessions_daily_with_app_role():
    """TASK-054: sesi habis/dicabut dibersihkan harian lewat container backend (role aplikasi), dan dicek clau-vps2-check."""
    timer = unit("clau2-purge-sessions.timer")
    assert timer["OnCalendar"] == ["*-*-* 04:30:00 Asia/Makassar"] and timer["Persistent"] == ["true"]
    service = unit("clau2-purge-sessions.service")
    assert service["ExecStart"] == ["/usr/bin/docker compose exec -T backend python -m app.auth.cli purge-sessions"]
    assert service["WorkingDirectory"] == ["/srv/clau/clau-ai-agents"]
    setup = (DEPLOY / "vps2-setup.sh").read_text()
    assert "clau2-purge-sessions.timer >/dev/null" in setup, "timer wajib di-enable, bukan hanya dipasang"
    assert "clau2-purge-sessions.service" in (DEPLOY / "vps2-check.sh").read_text()


def test_restore_is_never_automatic():
    """Pemulihan hanya lewat clau-vps2-restore yang diketik manusia: tidak ada timer/deploy/backup yang memanggilnya."""
    for path in [*DEPLOY.glob("*.sh"), *UNITS.iterdir()]:
        if path.name in ("vps2-restore.sh", "vps2-setup.sh", "vps2-check.sh"):
            continue
        text = path.read_text()
        assert "clau-vps2-restore" not in text.replace("Pemulihan: sudo clau-vps2-restore", ""), path.name
        assert "db-restore.sh --yes" not in text, path.name
    restore = (DEPLOY / "vps2-restore.sh").read_text()
    assert '[ "$answer" = PULIHKAN ]' in restore
    assert 'Enter = batal' in restore and "pick=" not in restore.split("read -rp")[0], "tidak boleh ada pilihan default"


def test_restore_commands_never_read_the_operator_keyboard():
    """docker compose exec membaca stdin: tanpa </dev/null jawaban PULIHKAN yang diketik ikut termakan (bug 2026-10-15)."""
    restore = (DEPLOY / "vps2-restore.sh").read_text()
    for call in ('"$OFFSITE" list', '"$OFFSITE" pull', "db-restore.sh --verify", "db-restore.sh --yes", '"$OFFSITE" push'):
        lines = [line for line in restore.splitlines() if call in line and not line.lstrip().startswith("#")]
        assert lines and all("</dev/null" in line for line in lines), call


def test_db_restore_backs_up_and_swaps_instead_of_overwriting():
    restore = (ROOT / "scripts" / "db-restore.sh").read_text()
    yes = restore.split('if [[ "$mode" == "--verify" ]]', 1)[1].split("\nelse\n", 1)[1]
    yes = "\n".join(line for line in yes.splitlines() if not line.lstrip().startswith("#"))
    # Backend berhenti dulu (tidak ada tulisan yang terlewat), lalu isi sekarang di-backup, baru restore.
    assert 'WRITERS="backend worker"' in yes, "semua service yang menulis ke database (termasuk worker AI) berhenti"
    assert yes.index("docker compose stop $WRITERS") < yes.index("db-backup.sh sebelum-restore") < yes.index('restore_into "$new"')
    assert "trap '' HUP INT TERM" in yes and "set +e" in yes, "restore tidak boleh berhenti setengah jalan"
    assert "string_agg(datname" in yes and "DROP DATABASE IF EXISTS $old" not in yes, "sisa restore terputus tidak dihapus diam-diam"
    assert "--clean" not in yes, "restore ke database baru, bukan menimpa (tabel skema baru menghalangi backup lama)"
    assert yes.index('restore_into "$new"') < yes.index('swap clau "$old"'), "database ditukar setelah restore lengkap"
    assert 'swap "$old" clau' in yes, "backend tidak sehat → isi sebelumnya kembali"


def test_backup_passphrase_never_on_command_line():
    """Argumen proses terbaca semua user (`ps`); passphrase hanya lewat environment."""
    for path in [ROOT / "scripts" / "db-backup.sh", ROOT / "scripts" / "db-restore.sh", *DEPLOY.glob("vps2-*.sh")]:
        text = path.read_text()
        assert "-hmac" not in text and "-pass pass:" not in text and "-k " not in text, path.name
    offsite = (DEPLOY / "vps2-offsite.sh").read_text()
    assert "--b2-account" not in offsite and "--b2-key" not in offsite, "key B2 lewat environment rclone"
    assert 'chmod 600 "$CONF"' in offsite and "read -rsp" in offsite


def test_backup_hmac_matches_openssl_format(tmp_path):
    """.hmac lama (openssl dgst -hmac) harus tetap cocok dengan scripts/backup_hmac.py."""
    sample = tmp_path / "clau-x.dump.enc"
    sample.write_bytes(bytes(range(256)) * 5000)
    key = "passphrase-uji-" + "a" * 40
    ours = subprocess.run(["python3", "-I", str(ROOT / "scripts" / "backup_hmac.py"), str(sample)],
                          env={"CLAU_HMAC_KEY": key, "PATH": "/usr/bin:/bin"}, capture_output=True, text=True, check=True).stdout.strip()
    theirs = subprocess.run(["openssl", "dgst", "-sha256", "-hmac", key, "-r", str(sample)],
                            capture_output=True, text=True, check=True).stdout.split()[0]
    assert ours == theirs


@pytest.mark.parametrize("name", ["../../etc/passwd", "clau-x.dump.enc", "clau-20261015T020000Z.dump.enc/../x", "a b"])
def test_offsite_pull_rejects_unknown_names(name, tmp_path):
    out = subprocess.run([str(DEPLOY / "vps2-offsite.sh"), "pull", name, str(tmp_path)], capture_output=True, text=True,
                         env={"PATH": "/usr/bin:/bin", "CLAU_OFFSITE_ENV": str(tmp_path / "tidak-ada.env")})
    assert out.returncode == 1 and "nama backup tidak valid" in out.stderr


def _restore_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "backups").mkdir(parents=True)
    (repo / "scripts").mkdir()
    (repo / "scripts" / "backup_hmac.py").write_text((ROOT / "scripts" / "backup_hmac.py").read_text())
    (repo / ".env").write_text("CLAU_BACKUP_PASSPHRASE=" + "p" * 64 + "\n")
    for name in ("clau-20261015T000000Z.dump.enc", "clau-20261015T060000Z-sebelum-restore.dump.enc", "catatan.txt"):
        (repo / "backups" / name).write_bytes(b"isi")
    env = {"PATH": "/usr/bin:/bin", "CLAU_REPO": str(repo), "CLAU_OFFSITE_ENV": str(tmp_path / "tidak-ada.env")}
    return repo, env


def test_restore_lists_backups_newest_first_in_wita(tmp_path):
    _, env = _restore_repo(tmp_path)
    out = subprocess.run([str(DEPLOY / "vps2-restore.sh"), "--list"], env=env, capture_output=True, text=True, check=True).stdout
    rows = [line for line in out.splitlines() if re.match(r"\s+\d+\. ", line)]
    assert len(rows) == 2, out  # file lain di backups/ diabaikan
    assert "2026-10-15 14:00 WITA" in rows[0] and "(isi sebelum restore)" in rows[0]
    assert "2026-10-15 08:00 WITA" in rows[1] and "B2 belum disetel" in out


@pytest.mark.parametrize(("answers", "message"), [
    ("\n", "dibatalkan"),               # Enter saja = batal (tanpa pilihan default)
    ("9\n", "dibatalkan"),              # nomor di luar daftar
    ("1\n", "passphrase salah"),        # .hmac tidak cocok + tidak ada jawaban passphrase
    ("", "dibatalkan"),                 # stdin habis
])
def test_restore_stops_before_touching_anything(tmp_path, answers, message):
    repo, env = _restore_repo(tmp_path)
    before = sorted(p.name for p in (repo / "backups").iterdir())
    out = subprocess.run([str(DEPLOY / "vps2-restore.sh")], input=answers, env=env, capture_output=True, text=True)
    assert out.returncode == 1 and message in out.stderr, out.stderr
    assert sorted(p.name for p in (repo / "backups").iterdir()) == before


def test_restore_replacement_server_rejects_bad_secret_key_without_changing_env(tmp_path):
    repo, env = _restore_repo(tmp_path)
    good = "p" * 64
    name = "clau-20261015T000000Z.dump.enc"
    mac = subprocess.run(["python3", "-I", str(ROOT / "scripts" / "backup_hmac.py"), str(repo / "backups" / name)],
                         env={"CLAU_HMAC_KEY": "lama" * 10, "PATH": "/usr/bin:/bin"}, capture_output=True, text=True, check=True).stdout
    (repo / "backups" / f"{name}.hmac").write_text(mac)
    before = (repo / ".env").read_text()
    for answers, message in ((f"2\n{good}\n", "passphrase tidak cocok"), (f"2\n{'lama' * 10}\npendek\n", "CLAU_SECRET_KEY tidak valid")):
        out = subprocess.run([str(DEPLOY / "vps2-restore.sh"), "--server-pengganti"], input=answers, env=env, capture_output=True, text=True)
        assert out.returncode == 1 and message in out.stderr, out.stderr
        assert (repo / ".env").read_text() == before


def test_backup_timer_does_not_open_dev_stderr():
    """Di bawah systemd stderr = socket journald: `tee /dev/stderr` gagal (ENXIO) dan backup terjadwal berhenti sebelum
    salinan B2 & uji restore (temuan audit 2026-10-15)."""
    for path in [*DEPLOY.glob("*.sh"), *(ROOT / "scripts").glob("*.sh")]:
        code = "\n".join(line for line in path.read_text().splitlines() if not line.lstrip().startswith("#"))
        assert "/dev/stderr" not in code, path.name
    backup = (DEPLOY / "vps2-backup.sh").read_text()
    line = next(line for line in backup.splitlines() if 'db-restore.sh --verify "$out"' in line)
    assert line.lstrip().startswith("if ") and "status=1" in line, "uji restore gagal harus terlapor"


def test_offsite_list_only_passes_exact_name_and_size(tmp_path):
    """Nama objek B2 = data tak tepercaya (siapa pun dengan key bucket): nama berspasi/$(…) tidak boleh sampai ke bash."""
    remote = tmp_path / "b2" / "bucket-uji" / "vps2"
    remote.mkdir(parents=True)
    for name in ("clau-20261015T020000Z.dump.enc", "clau-20261015T020000Z.dump.enc a[$(touch PWNED)]",
                 "clau-20261015T020000Z.dump.enc.hmac", "lain.txt"):
        (remote / name).write_bytes(b"x" * 7)
    conf = tmp_path / "offsite.env"
    conf.write_text(f"RCLONE_CONFIG_CLAUOFF_TYPE=alias\nRCLONE_CONFIG_CLAUOFF_REMOTE={tmp_path / 'b2'}\nCLAU_OFFSITE_BUCKET=bucket-uji\n")
    if subprocess.run(["bash", "-c", "command -v rclone"], capture_output=True).returncode:
        pytest.skip("rclone tidak terpasang (VPS 2 memasangnya lewat vps2-setup.sh)")
    out = subprocess.run([str(DEPLOY / "vps2-offsite.sh"), "list"], env={"PATH": "/usr/bin:/bin", "CLAU_OFFSITE_ENV": str(conf)},
                         capture_output=True, text=True, check=True, cwd=tmp_path).stdout
    assert out.splitlines() == ["clau-20261015T020000Z.dump.enc 7"]
    assert not (tmp_path / "PWNED").exists()


def test_restore_ignores_hostile_offsite_names(tmp_path):
    repo, env = _restore_repo(tmp_path)
    fake = tmp_path / "offsite-palsu.sh"
    fake.write_text("#!/bin/bash\n[ \"$1\" = list ] && printf '%s\\n' 'clau-20261016T000000Z.dump.enc a[$(touch PWNED)]' "
                    "'clau-20261016T000000Z.dump.enc 5 x' 'clau-20261017T000000Z.dump.enc 9'\n")
    fake.chmod(0o755)
    (tmp_path / "offsite.env").write_text("")
    env |= {"CLAU_OFFSITE_BIN": str(fake), "CLAU_OFFSITE_ENV": str(tmp_path / "offsite.env")}
    out = subprocess.run([str(DEPLOY / "vps2-restore.sh"), "--list"], env=env, capture_output=True, text=True, cwd=tmp_path)
    assert out.returncode == 0, out.stderr
    assert not (tmp_path / "PWNED").exists() and not (repo / "PWNED").exists()
    rows = [line for line in out.stdout.splitlines() if re.match(r"\s+\d+\. ", line)]
    assert len(rows) == 3 and "clau-20261017T000000Z.dump.enc" in rows[0] and "2026-10-16" not in out.stdout


def test_replacement_server_keys_written_only_after_lock():
    """--server-pengganti: kunci lama baru masuk .env setelah timer dijeda & lock didapat, dan dikembalikan saat keluar
    tanpa restore sukses (Ctrl-C / flock timeout tidak meninggalkan .env campuran)."""
    restore = (DEPLOY / "vps2-restore.sh").read_text()
    assert restore.index("flock -w 1200 9") < restore.index("set_env CLAU_SECRET_KEY")
    assert restore.index("trap cleanup EXIT") < restore.index("set_env CLAU_SECRET_KEY")
    assert 'if [ "$restored" != 1 ] && [ -f .env.sebelum-pengganti ]' in restore and "umask 077" in restore
