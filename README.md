# clau-agent

**Platform CLAU AI**: tempat agent menjalankan skill dari repo pilar untuk bisnis hospitality Indonesia. Repo ini berisi kode (frontend Next.js, backend FastAPI) dan **registry agent**. Aturan isi konten tidak ditulis di sini; aturan ada di [clau-core](https://github.com/deakasep/core) (submodule `core/`) dan repo pilar.

> **Status:** Public, hanya untuk dilihat ([LICENSE](./LICENSE)). Backend v0.10.0: PostgreSQL 16 (migrasi 0001–0007, termasuk level approval otomatis dari isi konten), login + 2FA wajib owner & content lead (QR & kode cadangan) + `/users`, backup terenkripsi tiap 6 jam + Backblaze B2, workflow request → draft → QA → approval dan fact sheet + Konfirmasi Fakta oleh klien (aturan Rule 08 dicek server & database), antrean AI menulis draft dengan AI fact-check & batas biaya (provider tiruan; provider Claude menyusul), dengan halaman UI-nya (`/requests`, `/fact-sheets`, `/ai-usage`). Status kerja terkini: [status & handoff](https://github.com/deakasep/content/blob/main/docs/status.md).

## Prinsip Platform

- Agent **menyiapkan draft**; publish, kirim ke tamu, ubah harga/ketersediaan, dan approval tetap dilakukan **manusia** (`core/AI-CONSTITUTION.md` §4).
- Tidak ada credential akun client di platform; integrasi mengikuti `core/shared/integrations.md`.
- Routing mengikuti `core/orchestrator/router.md`; registry di-test agar konsisten dengan router.

## Struktur

```text
clau-agent/
├── README.md · SUBMODULE.md · ACKNOWLEDGMENT.md · LICENSE
├── core/                 # submodule → clau-core
├── agents/
│   ├── README.md · registry.json   # agent → intent → skill/prompt/template di repo pilar
│   └── avatars/ · personas/ · evals/
├── backend/              # FastAPI: /health, /agents, /pillars, /route, /auth/*, /users, /requests, /drafts, /qa-records, /approvals
│   ├── app/main.py · app/workflow.py · app/auth/ · app/db/ · Dockerfile · requirements*.txt
│   ├── migrations/       # Alembic 0001–0005 (skema = core/shared/database-schema.md)
│   └── tests/            # API, auth, database sungguhan, konsistensi registry ↔ core router
├── frontend/             # Next.js 16 (App Router): registry agent, /login, /account, /users; Dockerfile
├── docs/                 # security.md, post-vps-checklist.md, deploy/vps-1-setup.md, deploy/vps-2-setup.md, design/
├── scripts/              # init-env.sh, db-backup.sh/db-restore.sh, sync-submodules.sh, check-core-pins.sh, deploy/ (VPS 1 & VPS 2)
├── docker-compose.yml    # backend + frontend dalam container (port hanya 127.0.0.1)
├── .env.example          # semua variabel environment (tanpa secret); salin ke .env
└── .github/workflows/    # ci.yml, cross-repo-validate.yml, sync-submodules.yml, notify-downstream.yml, main-guard.yml
```

## Setup

Panduan submodule (update, sync, troubleshooting, GitHub Actions): [SUBMODULE.md](./SUBMODULE.md).

```bash
git clone --recurse-submodules https://github.com/deakasep/agent.git
cd clau-agent

# Backend
cd backend && pip install -r requirements.txt && pytest && uvicorn app.main:app --reload

# Frontend (terminal lain)
cd frontend && npm install && npm run dev
```

### Docker (database + backend + frontend)

```bash
scripts/init-env.sh                        # sekali: .env (chmod 600) + password database acak
docker compose up -d --build --wait        # db → migrate → backend http://127.0.0.1:8000 · frontend http://127.0.0.1:3000
docker compose run --rm backend python -m app.db.seed   # opsional: 4 klien fiktif SIMULASI
docker compose run --rm backend python -m app.auth.cli create-owner --email <email> --name "<nama>"   # owner pertama
scripts/db-backup.sh                       # backup terenkripsi; uji: scripts/db-restore.sh --verify <file>
docker compose down                        # data tetap di volume db-data (hapus total: down -v)
```

- **Login:** semua halaman wajib login (`CLAU_AUTH_ENABLED=1`). Browser hanya bicara ke frontend; `/api/*` diteruskan server Next.js ke backend lewat jaringan internal (keputusan VPS #1). Sesi cookie aman + CSRF, 2FA wajib owner & content lead (QR + kode cadangan), tanpa pendaftaran publik; owner mengelola akun di `/users`. Detail: [backend/README.md](./backend/README.md#login--hak-akses-050-diperkuat-060). VPS 1 (tanpa backend) tetap pratinjau SIMULASI tanpa login.
- **Database:** PostgreSQL 16 tanpa port host. Service `migrate` (sekali jalan) membuat role & database lalu menjalankan migrasi Alembic; backend memakai **role aplikasi** tanpa hak DDL dan tidak pernah menerima password admin. Skema = `core/shared/database-schema.md`; Constraint Wajib ditegakkan di database (CHECK + trigger). Detail: [backend/README.md](./backend/README.md#database).

- **Environment:** semua variabel ada di [`.env.example`](./.env.example) beserta artinya. `.env` tidak di-commit; secret (password database, API key AI, WhatsApp) hanya di `.env` lokal/server, tidak pernah di repo ([docs/security.md](./docs/security.md) § 6). Test `backend/tests/test_env.py` memastikan setiap variabel yang dibaca kode tercantum dan tidak ada secret di template.
- **Image:** `backend/Dockerfile` (Python 3.12, dependency runtime saja: `backend/requirements-runtime.txt`) dan `frontend/Dockerfile` (Node 22, Next.js output standalone). Base image dipin ke digest dan diperbarui Dependabot. Build context = root repo dengan `.dockerignore` allowlist, jadi `.env`, `.git`, dan `core/` tidak pernah ikut ke image.
- **Pengamanan container:** user non-root, filesystem read-only, tanpa capability Linux, `no-new-privileges`, batas memori & proses, port hanya di `127.0.0.1` (publik lewat Nginx + TLS). Dicek job CI `docker`.
- **VPS 1** tetap memakai deploy tarik + systemd dengan user khusus `clau-web` / `clau-deploy` dan cek harian `clau-vps1-check` ([docs/deploy/vps-1-setup.md](./docs/deploy/vps-1-setup.md)); compose ini dipakai untuk kerja lokal dan untuk **VPS 2** (backend + database + login lewat HTTPS Tailscale sampai ada domain, deploy otomatis dengan rollback, backup tiap 6 jam + Backblaze B2, pemulihan `clau-vps2-restore`; [docs/deploy/vps-2-setup.md](./docs/deploy/vps-2-setup.md)).

## Roadmap Platform

| Tahap | Isi | Status |
|---|---|---|
| 0 | Scaffold + registry + router statis | ✅ |
| 1 · PR 1 | Database sesuai `core/shared/database-schema.md` (PostgreSQL 16, Constraint Wajib di database) | ✅ 0.4.0 |
| 1 · PR 2 / 2b | Login, hak akses, 2FA, `/users`, backup terenkripsi, audit keamanan | ✅ 0.5.0 / 0.6.0 |
| 1 · PR 3 | Request → draft → QA → approval di API (Rule 08 dicek server & database) | ✅ 0.7.0 |
| 1 · PR 3b | Kelola klien, fact sheet & Konfirmasi Fakta; UI workflow | ✅ 0.8.0 |
| 2 | Antrean AI menulis draft + AI fact-check + batas biaya (provider tiruan; provider Claude = PR 4c) | ✅ 0.9.0 (provider nyata belum) |
| 2 · TASK-054 | 2FA wajib content lead, pembersihan sesi harian, rotasi secret | ✅ 0.9.1 |
| 2 · TASK-032 | Penanda isi konten & level approval otomatis (Rule 08) | ✅ 0.10.0 |

Setiap tahap tetap Level 1 otomasi (manusia yang publish), kecuali owner menyetujui level lebih tinggi lewat revisi Constitution.

## Lisensi

Proprietary, source-available (hanya untuk dilihat; tidak boleh disalin, dipakai, atau dipakai melatih AI tanpa izin tertulis). Lihat [LICENSE](./LICENSE).
