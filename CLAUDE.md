# CLAUDE.md — clau-agent

> Peta repo untuk AI agent. Baca file ini dulu sebelum menjelajah repo. Last updated: 2026-10-22

> 🔔 **Sesi baru: baca [status & handoff CLAU AI](https://github.com/deakasep/content/blob/main/docs/status.md) dulu** (otoritas, keputusan yang sudah diambil, status, pekerjaan terbuka). Repo Jerco milik Pak Indra: jangan disentuh tanpa persetujuan beliau.

## 1. Identitas

| Item | Nilai |
|---|---|
| Repo | `deakasep/agent` (public, hanya untuk dilihat; LICENSE) |
| Peran | Platform: registry agent, backend FastAPI, frontend Next.js |
| Submodule | `core/` → clau-core |
| Status | Backend v0.14.0: **kredit top up hangus 12 bulan** (migrasi 0011 `topup_expire`, `app/billing/topup_expiry.py`: pemakaian top up urut kedaluwarsa terdekat, `Wallet.topup_next_expiry` di `/billing`; model kredit Sintra.ai) + **klien mandiri memakai agen sendiri** (migrasi 0010 `clients.self_serve`: pemilik usaha mengisi Brain bisnis, meminta draft AI, dan menyetujui hasil agen tanpa staf; UI langkah awal di beranda, `/fact-sheets` = Brain bisnis) + **pendaftaran mandiri** (`app/auth/signup.py`, `app/mail.py`: daftar → verifikasi email → pilih paket, lupa/reset password; mati secara default `CLAU_SIGNUP_ENABLED`; migrasi 0009; UI `/daftar`, `/verifikasi-email`, `/lupa-password`, `/reset-password`) + **langganan & kredit** (`app/billing/`: paket 1/3/6/12 bulan, kredit bulanan + top up, pemotongan & refund kredit job AI, Midtrans webhook / mode uji; migrasi 0008; UI `/billing`) + API registry + login & hak akses (sesi cookie, CSRF, 2FA wajib owner & content lead dengan QR & kode cadangan, `/users` owner) + workflow request → draft → QA → approval (`app/workflow.py`) + klien, fact sheet & Konfirmasi Fakta (`app/facts.py`), matriks izin Rule 08 dengan aturan di database, + **antrean AI menulis draft** (`app/ai/`: job, worker container terpisah, AI fact-check, batas biaya; provider tiruan, provider Claude menyusul PR 4c) + **penanda isi konten & level approval otomatis** (Rule 08: harga/promo, orang, iklan, review negatif, agama/adat, terjemahan ikut draft asal; migrasi 0007) di atas PostgreSQL 16 (migrasi 0001–0010), backup terenkripsi. UI: `/requests` (termasuk *Buat draft dengan AI*), `/fact-sheets`, `/ai-usage` (owner), tambah klien di `/users`. Belum: provider AI nyata |

## 2. Peta File

| Path | Fungsi |
|---|---|
| `agents/registry.json` | `pillars` (5 pilar v2, sama dengan `core/README.md`) + 15 agent (`autonomy_max` = kolom Otonomi router) → nama (`display_name`), avatar, intent → skill/prompt/template di repo pilar; `default_forbidden_actions`; link `persona` & `evals` |
| `agents/avatars/` | Master avatar 3D per agent + README (aturan, status gambar); crop UI di `frontend/public/agents/`; dijaga `backend/tests/test_avatars.py` |
| `agents/personas/` | Kartu persona per agent (gaya bahasa, etika, batas & eskalasi, contoh) |
| `agents/evals/` | Kasus uji per agent + `run_evals.py` + rubrik "seperti manusia ahli" |
| `backend/app/ai/` | Tahap 2: `routes.py` (`/requests/{id}/ai-drafts`, `/ai-jobs`, `/ai-usage`, `/ai-budgets`), `worker.py` (antrean SKIP LOCKED, retry, `python -m app.ai.worker`), `factcheck.py` (fakta klien + AI fact-check), `prompt.py` (penyamaran + prompt stabil), `provider.py` (antarmuka + provider tiruan), `budget.py`. Aturan data: core AI-BOUNDARY § Data ke Provider AI |
| `backend/app/main.py` · `backend/app/workflow.py` · `backend/app/facts.py` | `GET /health`, `GET /agents`, `GET /pillars`, `POST /route` · `/requests`, `/drafts`, `/qa-records`, `/approvals` (aturan data migrasi 0004) · `/clients`, `/fact-sheets` (aturan data migrasi 0005); peran & isolasi klien di API; tanpa endpoint publish. Inventaris endpoint & jembatan frontend dikunci `tests/test_security.py` |
| `backend/app/auth/` | Login, sesi, CSRF, 2FA TOTP + kode cadangan, hak akses dari `memberships` (`access.py`), `/users` (owner), CLI `create-owner` / `reset-mfa` / `purge-sessions` |
| `backend/app/db/` · `backend/migrations/` | Model SQLAlchemy (22 tabel `core/shared/database-schema.md`), bootstrap role (migrasi vs aplikasi), seed SIMULASI; migrasi Alembic + trigger Constraint Wajib. Ubah skema = migrasi baru |
| `backend/tests/` | Test API, konsistensi registry ↔ `core/orchestrator/router.md` & tabel pilar `core/README.md`, persona & eval, `test_db.py` (Constraint Wajib ke PostgreSQL sungguhan; butuh `CLAU_TEST_DB_ADMIN_URL`), `test_workflow.py` (matriks izin, IDOR, aturan approval lewat API), `test_facts.py` (fact sheet & Konfirmasi Fakta) |
| `frontend/` | Next.js App Router; halaman registry agent, `/login`, `/account`, `/users` (owner, juga tambah klien), `/requests` & `/requests/[id]` (draft, QA, keputusan), `/fact-sheets` & `/fact-sheets/[id]` (Konfirmasi Fakta), `/ai-usage` (owner: biaya & batas AI); `components/AiPanel.tsx` + `lib/ai.ts` = UI antrean AI; `app/api/[...path]` = jembatan ke backend; `proxy.ts` = penjaga halaman bila `CLAU_AUTH_ENABLED=1` |
| `scripts/` | `init-env.sh`, `db-backup.sh` / `db-restore.sh` (backup terenkripsi + uji restore; `backup_hmac.py`, `db-summary.sql`), `sync-submodules.sh`, `check-core-pins.sh`, `deploy/` (VPS 1 `vps1-*`: `vps1-setup.sh` = VPS 1 baru/pengganti satu perintah; VPS 2 `vps2-*`) |
| `.env.example` | Semua variabel environment + arti & default aman; tanpa secret (dites `backend/tests/test_env.py`) |
| `docker-compose.yml` · `backend/Dockerfile` · `frontend/Dockerfile` · `.dockerignore` | Container backend + frontend: non-root, read-only, port 127.0.0.1; base image dipin digest; dicek job CI `docker` |
| `SUBMODULE.md` | Panduan submodule & GitHub Actions |
| `.github/workflows/` | `ci.yml` (`backend`, `frontend`, `audit`, `docker`, `release-vps1`), `cross-repo-validate.yml`, `sync-submodules.yml`, `notify-downstream.yml`, `main-guard.yml` |
| `backend/README.md` · `frontend/README.md` | Detail backend (auth, database, backup) · halaman & data frontend |
| `docs/deploy/vps-1-setup.md` | VPS 1 (pratinjau, tanpa login, tanpa data): § 0 VPS baru/pengganti satu perintah (`vps1-setup.sh`), auto-deploy, user khusus, `clau-vps1-check` |
| `docs/deploy/vps-2-setup.md` | VPS 2 (backend + database + login, tanpa domain: HTTPS Tailscale khusus tailnet): `scripts/deploy/vps2-setup.sh`, deploy otomatis dengan rollback skema, backup terenkripsi tiap 6 jam + Backblaze B2, pemulihan manual `clau-vps2-restore` (§ 5, termasuk server pengganti), `clau-vps2-check` |
| `docs/security.md` | Audit & aturan keamanan: header, Nginx, sandbox systemd, supply chain; **aturan wajib sebelum login/DB/AI/WhatsApp di VPS 2** (§ 6) |
| `.claude/` | Komponen Claude buatan Anthropic yang direview & dikunci commit: `/code-review`, `/review-pr` + 6 agen pemeriksa; daftar, lisensi & aturan keamanan di `.claude/VENDORED.md` |
| `docs/post-vps-checklist.md` | **Pengingat:** langkah wajib setelah VPS 1 & 2 siap (AI provider, eval 33 kasus, aktivasi pilar 2–4) |

> 🔔 **Pengingat untuk agent:** bila owner menyebut VPS sudah siap, buka `docs/post-vps-checklist.md` dan ingatkan langkah-langkahnya.

## 3. Command

```bash
git submodule update --init
cd backend && pip install -r requirements.txt && pytest
python agents/evals/run_evals.py --check
cd frontend && npm ci && npm run build
scripts/init-env.sh && docker compose up -d --build --wait   # db + migrate + backend + frontend; docker compose down
```

Spesifikasi UI/UX (Portal Klien & Studio) dan design tokens ada di repo arsip `clau-content/design/`.

## Aturan Kerja untuk Agent

- Baca `core/AGENTS.md` (instruksi agent lintas repo) dan, untuk aturan induk, `core/AI-CONSTITUTION.md` + `core/AI-BOUNDARY.md`.
- **Otoritas perubahan:** dokumen berstatus Approved hanya diubah atas perintah **Pak Indra** atau **Dea Karisna (d34faiza)**.
- AI **tidak** publish, kirim ke pihak luar, atau self-approve. Review independen L2/L3 = manusia.
- **Jangan** commit data client nyata (brief, fact sheet, caption, harga, foto, data tamu), `.env`, atau credential. Data client nyata ada di Client Workspace (Drive), bukan repo.
- Label evidence dipakai persis: `DATA FINAL`, `ASSUMPTION`, `CLIENT CONFIRMATION`, `FIELD VERIFICATION`, `RISK`, `NEXT ACTION`.
- Commit message: `feat:`, `fix:`, `docs:`, `refactor:`, `chore:`, `test:`. Jalankan validator sebelum push.
- `main` wajib lewat PR dengan CI hijau (`backend`, `frontend`, `audit`, `docker`, `cross-validate`; dijaga `main-guard`). VPS 1 menayangkan `release/vps1` = commit `main` yang CI-nya hijau (job `release-vps1`); jangan push manual ke branch itu.

- **Tidak boleh** ada endpoint/tombol publish ke platform sosial. Aturan approval (fakta dikonfirmasi, review independen) wajib dicek di server, bukan hanya di UI.

- Entry point lintas AI: [AGENTS.md](./AGENTS.md). ChatGPT/Codex dan Claude menyelesaikan coding PR yang sudah diizinkan sampai merge setelah seluruh CI wajib hijau, sesuai core AI-BOUNDARY.

## Hemat kuota: satu chat per topik (perintah owner, 2026-11-01)

- **Satu chat = satu topik/tugas** (mis. web CLAU, JASA, video agen). Chat panjang membuat setiap balasan membaca ulang seluruh riwayat, jadi kuota cepat habis.
- **Di akhir setiap tugas** perbarui file status (CLAU: [content `docs/status.md`](https://github.com/deakasep/content/blob/main/docs/status.md); JASA: `jasa/STATUS.md`) supaya chat baru langsung nyambung.
- **Chat baru** cukup dibuka owner dengan "lanjutkan dari status": AI membaca file status dulu, tidak menanyakan ulang hal yang sudah diputuskan.
- Bila chat sudah panjang atau topik berganti, AI menyarankan owner membuka chat baru (satu kalimat), **setelah** status diperbarui dan semua kerja di-push.
