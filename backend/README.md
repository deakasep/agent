# Backend (FastAPI)

API registry agent, router statis, login & kelola user (`/auth/*`, `/users`), workflow request → draft → QA → approval (`/requests`, `/drafts`, `/qa-records`, `/approvals`, 0.7.0), serta klien, fact sheet & Konfirmasi Fakta (`/clients`, `/fact-sheets`, 0.8.0). **Tidak ada** endpoint yang publish konten, mengirim pesan ke tamu, atau mengubah sistem client (`core/AI-CONSTITUTION.md` §4). Kontrak: `core/shared/api-contracts.md`.

## Jalankan

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload          # http://127.0.0.1:8000/docs
pytest                                  # test API + konsistensi registry ↔ core router
```

`requirements.txt` = semua dependency (termasuk test). `requirements-runtime.txt` = yang masuk image Docker saja; pin keduanya harus sama (dites `tests/test_env.py`). Image: `docker build -f backend/Dockerfile -t clau-backend .` dari root repo, atau `docker compose up` (lihat README root). Variabel environment: [`../.env.example`](../.env.example).

## Endpoint

| Method & path | Fungsi |
|---|---|
| `GET /health` | Status service |
| `GET /agents` | Daftar agent dari `../agents/registry.json` + forbidden actions |
| `GET /pillars` | 5 pilar dari `../agents/registry.json` (nama, status, repo) + id agent per pilar |
| `POST /route` | `{"intent": "caption"}` → agent, pilar, skill, repo, approval minimum, otonomi maksimum (`autonomy_max`), status |
| `/auth/*`, `/users` | Login, akun, 2FA, kelola user (owner); § Login & Hak Akses |
| `/requests`, `/drafts`, `/qa-records`, `/approvals` | Workflow (POST + GET list/detail); § Workflow |

## Keamanan

Input dibatasi, body ≤ 64 KB, Host divalidasi, header keamanan di setiap respons, tanpa CORS, error tanpa detail internal, `/docs` mati bila `CLAU_ENV=production`. Detail dan cara menjalankan di produksi: [`../docs/security.md`](../docs/security.md) § 3; tes: `tests/test_security.py`.

## Database

PostgreSQL 16 (SQLAlchemy 2 + Alembic + psycopg 3). Skema mengikuti kontrak [`core/shared/database-schema.md`](../core/shared/database-schema.md): 22 tabel di `app/db/models.py`, migrasi di `migrations/versions/`.

| Aturan (Constraint Wajib kontrak) | Ditegakkan oleh |
|---|---|
| Mode SIMULASI tidak pernah `Approved` | CHECK `ck_approvals_simulasi_not_approved` |
| Mode approval = mode draft | trigger `clau_approval_rules` |
| Approval L2/L3 butuh claim verification **independen terakhir** yang `Pass`/`Conditional` (Fail yang lebih baru membatalkan) | trigger `clau_approval_rules` |
| Tidak ada catatan tayang tanpa approval `Approved` untuk versi draft yang sama | trigger `clau_publication_requires_approval` |
| `DATA FINAL` wajib sumber + tanggal sumber | CHECK `ck_claims_data_final_sourced` |
| Reviewer independen ≠ pembuat draft; agent tidak pernah independen | trigger `clau_qa_reviewer_not_author` + CHECK `ck_qa_records_independent_is_human` |
| Approval terikat versi: isi draft yang tersimpan tidak bisa diubah (revisi = versi baru) | trigger `clau_draft_version_immutable` |
| `audit_log` append-only (juga untuk pemilik tabel) | trigger + hak UPDATE/DELETE/TRUNCATE dicabut |
| Label evidence, kategori klaim, vertical, priority, level, peran: nilai persis | CHECK (sumber enum: `content-brief.schema.json`, priority engine, rule 08) |

Pelanggaran aturan = error SQLSTATE `23514` dengan pesan berawalan kode aturan (mis. `approval_needs_independent_review: …`), siap dipetakan ke error kontrak API.

**Role terpisah** (`app/db/bootstrap.py`, docs/security.md § 6): role migrasi = pemilik schema; role aplikasi = SELECT/INSERT/UPDATE/DELETE saja (tanpa CREATE/ALTER/DROP/TRUNCATE). Password SCRAM-SHA-256. Database tanpa port host.

```bash
# Dengan Docker (dari root repo): migrasi jalan otomatis di service `migrate`
docker compose run --rm backend python -m app.db.seed     # data contoh SIMULASI (idempoten)

# Ubah skema: ubah app/db/models.py, lalu buat migrasi baru (jangan ubah migrasi yang sudah di main)
CLAU_MIGRATION_DATABASE_URL=postgresql+psycopg://clau_migrator:<pw>@127.0.0.1:5432/clau \
  alembic revision --autogenerate -m "<ringkas>"
```

**Test database** (`tests/test_db.py`, 31 test) butuh PostgreSQL: set `CLAU_TEST_DB_ADMIN_URL` ke superuser Postgres sekali pakai, mis. `docker run -d -e POSTGRES_PASSWORD=x -p 127.0.0.1:55432:5432 postgres:16` lalu `CLAU_TEST_DB_ADMIN_URL=postgresql://postgres:x@127.0.0.1:55432/postgres pytest`. Tanpa variabel itu test database dilewati; di CI wajib (`CLAU_REQUIRE_DB_TESTS=1`). Test juga memastikan model = migrasi, migrasi bisa downgrade/upgrade, dan tabel = kontrak core.

## Login & Hak Akses (0.5.0, diperkuat 0.6.0)

Kontrak endpoint: [`core/shared/api-contracts.md`](../core/shared/api-contracts.md). Kode: `app/auth/`.

| Aspek | Implementasi |
|---|---|
| Password | Argon2id (RFC 9106), min. 12 karakter, tidak memuat nama email (NIST SP 800-63B, tanpa aturan komposisi). Rehash otomatis bila parameter naik |
| Sesi | Token acak 256-bit di cookie `__Host-clau_session` (`HttpOnly; Secure; SameSite=Lax; Path=/`); database hanya menyimpan SHA-256-nya. Habis setelah 120 menit tidak aktif / 12 jam. Token baru setiap login, ganti password, dan aktifkan 2FA |
| CSRF | Header `X-CSRF-Token` = HMAC(`CLAU_SECRET_KEY`, token sesi) untuk semua POST/PUT/PATCH/DELETE; Origin & `Sec-Fetch-Site` lintas situs ditolak |
| Brute force | 5 gagal per email (juga email tidak terdaftar) = 429 selama 15 menit; akun terdaftar juga dikunci di database dan semua sesinya diputus. Respons **dan waktu respons** email tidak terdaftar/nonaktif = password salah (Argon2 selalu dijalankan). Password salah saat ganti password / buat kode cadangan juga dihitung. Hashing Argon2 dibatasi 3 bersamaan (`CLAU_HASH_CONCURRENCY`) agar banjir login tidak menghabiskan memori. Batas per IP di Nginx saat deploy |
| 2FA | TOTP (RFC 6238), **wajib untuk owner**, aktivasi lewat **QR code** (dibuat di server); secret terenkripsi AES-GCM terikat id user; kode tidak bisa dipakai ulang, juga saat dikirim bersamaan (UPDATE atomik). **10 kode cadangan** sekali pakai (HMAC, ditampilkan sekali; buat ulang dengan password). HP hilang tanpa kode cadangan: `python -m app.auth.cli reset-mfa --email …` di server |
| Perangkat | `Me.active_sessions`; **keluar dari semua perangkat** (`POST /auth/logout-all`). Sesi habis/dicabut dibersihkan saat login dan lewat `python -m app.auth.cli purge-sessions` (jadwalkan harian) |
| Akun | Tidak ada pendaftaran publik. Owner pertama: `python -m app.auth.cli create-owner --email … --name …` (password lewat prompt tersembunyi). User lain dibuat owner (`POST /users`) dengan password sementara yang wajib diganti |
| Hak akses | `app/auth/access.py`: peran dari `memberships`; staf agency melihat semua klien, `client_approver`/`viewer` klien hanya klien miliknya; level approval maksimal per klien. Owner tidak bisa menonaktifkan diri / menghapus owner terakhir (dijaga advisory lock Postgres, aman saat dua owner mengubah bersamaan). Halaman **`/users`** untuk owner |
| Password | Ditolak juga bila hanya kata umum + angka/simbol (`app/auth/common_passwords.txt`, mis. `Password2026!!`, `bismillah12345`) atau urutan angka/huruf |
| Fail closed | `CLAU_SECRET_KEY` kosong/pendek → 503 `auth_unavailable`; database tidak ada → 503 `database_unavailable` |
| Audit | `audit_log`: login, gagal login, logout, ganti password, 2FA aktif/reset, user dibuat/nonaktif/aktif, peran berubah |

```bash
# Owner pertama (sekali), dari root repo:
docker compose run --rm backend python -m app.auth.cli create-owner --email owner@contoh.id --name "Nama Owner"
# Login di http://127.0.0.1:3000 → aktifkan 2FA (wajib owner & content lead) → kelola user lewat API /users
```

Test: `tests/test_auth.py` (53 test ke PostgreSQL sungguhan, termasuk replay kode 2FA, rotasi sesi, CSRF, Origin, penguncian, owner terakhir, timing email, kode cadangan). Audit keamanan menyeluruh 2026-10-13: 22 temuan, semua ditutup di 0.6.0.

## Backup & Restore

```bash
scripts/db-backup.sh                                   # backups/clau-<UTC>.dump.enc + .hmac (chmod 600)
scripts/db-restore.sh --verify backups/clau-….dump.enc # uji restore ke database sementara (bulanan)
scripts/db-restore.sh --yes    backups/clau-….dump.enc # ganti isi database: backup isi sekarang dulu, restore ke database baru, tukar, cek sehat
```

`pg_dump` → AES-256 (PBKDF2 600.000 iterasi) dengan `CLAU_BACKUP_PASSPHRASE`, HMAC-SHA256 dicek sebelum restore (file diubah = ditolak; `scripts/backup_hmac.py`, passphrase lewat environment, tidak pernah jadi argumen proses). `--verify` mencetak ringkasan isi (`scripts/db-summary.sql`). Passphrase disimpan owner terpisah dari backup. Di VPS 2: backup tiap 6 jam + Backblaze B2 dan pemulihan `sudo clau-vps2-restore` ([`docs/deploy/vps-2-setup.md`](../docs/deploy/vps-2-setup.md) § 5). Backup, uji, dan restore penuh (termasuk backup skema lama dan pembatalan otomatis) dites di CI job `docker`.

## Workflow (0.7.0, Tahap 1 PR 3)

Request → draft (ditulis manusia) → QA → approval, sesuai kontrak `core/shared/api-contracts.md` § Matriks Izin Workflow dan `clau-market/rules/08`. Kode: `app/workflow.py`; aturan data di migrasi `0004`.

| Hal | Cara |
|---|---|
| Request | `pillar` & `approval_min` dari registry (router), `priority` dari priority engine (urgensi dari `deadline` WITA + `impact` + `risk`). Intent pilar planned boleh dicatat, draft-nya ditolak `intent_not_active` |
| Draft | Ditulis staf agency; versi = berikutnya (request dikunci), `mode` dari `clients.simulation`, `skill` dari registry. Klaim fakta wajib `fact_key`; brief/fact sheet harus milik klien yang sama. Revisi = draft versi baru |
| QA | `independent = true` hanya owner/content lead dan bukan pembuat draft; content staff = pre-check |
| Approval | Approver klien (sampai `max_level`), atau owner/content lead yang mencatat persetujuan tertulis klien (`channel_ref` `https://`/`mailto:`/`workspace://` wajib untuk Approved, semua level). Database menolak (semua keputusan): peran tidak sesuai membership, pembuat memutuskan sendiri, level < minimum draft (risk 3 = L3; klaim fakta = min. L2), request sudah selesai; dan untuk Approved: versi lama, fakta belum dikonfirmasi, SIMULASI |
| Isolasi klien | Approver/viewer klien hanya melihat kliennya; detail klien lain = 404, list `client_code` klien lain = 403. Peran, id user, mode, versi, pilar, prioritas tidak pernah dari body (`extra = forbid`) |
| Jejak | Setiap POST menulis `audit_log` (tanpa isi konten); klaim, QA, dan approval append-only |

Test: `tests/test_workflow.py` (alur utuh, matriks izin per peran, IDOR, aturan sampai ke pengguna, race versi draft) dan `tests/test_db.py` (setiap aturan di database, race approval vs draft baru, upgrade dari 0003 dengan data lama). Uji mutasi: 28 pengaman dirusak satu per satu, semua tertangkap.

## Fact Sheet & Konfirmasi Fakta (0.8.0, Tahap 1 PR 3b)

Alur `design/user-flow/client-portal-flow.md` § Konfirmasi Fakta; kode `app/facts.py`, aturan data di migrasi `0005`.

| Hal | Cara |
|---|---|
| Klien | `GET /clients` (hanya klien yang boleh dilihat), `POST /clients` khusus owner (`simulation = true` = klien fiktif, drafnya selalu SIMULASI) |
| Fact sheet | Disusun staf agency: versi = berikutnya per klien (klien dikunci) + daftar fakta (`facts`, kategori faktual, `fact_key` berawalan kategori, unik per versi). Belum disetujui saat dibuat |
| Jawaban fakta | `confirmed` atau `corrected` + nilai yang benar, oleh approver klien itu, atau owner/content lead yang mencatat jawaban tertulis klien (`channel_ref` wajib). Pembuat fact sheet tidak menjawab faktanya. Append-only; yang berlaku jawaban terakhir. `value_before` diisi database |
| Persetujuan | Setelah semua fakta dijawab; oleh peran yang sama (agency wajib `approval_ref`, bukan pembuatnya). Sesudah itu fact sheet, fakta, dan jawabannya beku: perubahan = versi baru |
| Ke draft | Draft dengan klaim ber-`fact_key` + `fact_sheet_id` fact sheet yang disetujui bisa di-approve (aturan `facts_unconfirmed` 0.7.0) |
| Jejak | `audit_log` mencatat id, kunci fakta, dan keputusan; **tanpa** nilai fakta (data klien) |

Test: `tests/test_facts.py` (alur utuh sampai approval L2, siapa boleh apa, isolasi klien, validasi, audit tanpa nilai) dan `tests/test_db.py` (aturan migrasi 0005, upgrade dari 0004 dengan fact sheet lama). Uji mutasi: 35 pengaman dirusak satu per satu, 34 tertangkap; satu lolos karena pengaman lapis kedua yang sudah dicakup aturan lain (persetujuan lewat alur klien).

## Penanda Isi Konten & Level Approval Otomatis (0.10.0, TASK-032)

Rule 08 menetapkan level approval dari **isi** konten. Kontrak: `core/shared/api-contracts.md` § Penanda Isi Konten; keputusan owner K1–K6 di `clau-content/docs/review-packet-task-032.md`. Aturan data di migrasi `0007`; API di `app/workflow.py`.

| Hal | Cara |
|---|---|
| Penanda | `price_promo`, `people`, `ota_listing` = L2; `negative_review`, `paid_ads`, `influencer`, `religion_culture`, `crisis` = L3 (tabel `draft_flags`) |
| Wajib dinyatakan | `POST /drafts` wajib `content_flags` (daftar kosong = pembuat menyatakan tidak ada); UI meminta centang eksplisit "tidak ada satu pun" |
| Jaring pengaman | Trigger database menambah penanda `server` untuk setiap draft (API & worker AI): kata harga (`Rp`/`IDR` + angka, `%`, harga, diskon, promo, discount, price, rate, paket + angka), kata agama/adat yang spesifik (bukan "upacara"/"sakral" yang umum di konten wedding), `review-reply` rating ≤ 3, intent `ota-listing`. Daftar kata hanya di `clau_auto_flags` (migrasi 0007) |
| Versi baru | Mewarisi penanda aktif non-server versi sebelumnya (trigger); level tidak bisa turun diam-diam |
| Tambah / hapus | Tambah: staf agency (`staff`, atau `qa` bila sudah mencatat QA di draft itu). Hapus: owner/content lead, alasan 10–500 karakter, audit log; penanda `server` tidak bisa dihapus (`flag_not_removable`); DELETE dicabut dari role aplikasi |
| Request | `review-reply` wajib `review_rating` 1–5; `localize` wajib `source_draft_id` (klien sama); keduanya tidak bisa diubah |
| Level minimum | `clau_draft_level_reasons` / `clau_draft_min_level` (dipakai trigger approval dan `GET /drafts/{id}` → `min_level`, `min_level_reasons`): intent (risk 3 = L3), klaim fakta L2, draft AI klien nyata L2, penanda aktif, draft asal untuk `localize` |

Test: `tests/test_workflow.py` (setiap celah di paket keputusan: review negatif, terjemahan, harga di teks, orang, iklan/influencer, agama/adat; tambah/hapus penanda; pewarisan versi; aturan langsung di database) dan `tests/test_db.py` (upgrade 0006 → 0007 memberi penanda pada draft lama).

## AI Menulis Draft (0.9.0, Tahap 2 PR 4b)

Kontrak: `core/shared/api-contracts.md` § AI Menulis Draft; aturan data: `core/AI-BOUNDARY.md` § Data ke Provider AI (v1.4.0). Kode: `app/ai/`.

| Bagian | Isi |
|---|---|
| Alur | `POST /requests/{id}/ai-drafts` → job `ai_jobs` (`queued`) → **worker** `python -m app.ai.worker` (service `worker`, container terpisah) → draft versi baru (`created_by` NULL, `agent_id`) + klaim + QA otomatis → review & approval manusia. Tidak ada publish |
| AI fact-check | Label bukti ditentukan worker, bukan model: klaim faktual dengan `fact_key` di fact sheet terbaru yang disetujui, kategori sama, dan nilai fakta tertulis di teks klaim = `DATA FINAL` (sumber + tanggal jawaban klien, WITA); tanpa fakta / isi tidak cocok = `RISK` (approval terkunci `facts_unconfirmed`); kategori tak dikenal = `RISK` `other.tanpa-kategori`; `experience`/`other` = `ASSUMPTION`; > 30 klaim = job `invalid_output`. QA otomatis `claim-verification` Pass/Fail, `independent` false |
| Data ke provider | Hanya fakta yang dikonfirmasi klien (nilai koreksi terakhir) + teks request yang disamarkan (`app/ai/prompt.redact`: email, telepon, kode booking/PNR/voucher, nomor kamar, deret angka panjang → `<KONTAK>` / `<NO_BOOKING>` / `<NO_KAMAR>`; harga, tanggal, jam, kode promo tetap utuh). Prompt urut stabil → bisa di-cache provider; `prompt_version` dicatat |
| Pengaman | `CLAU_AI_ENABLED=1` wajib (tombol mati global: job antre langsung `ai_disabled`, hasil panggilan yang sedang berjalan tidak disimpan); `CLAU_AI_INTENTS` (default `caption`); provider tiruan (`fake`) hanya untuk klien SIMULASI; fact sheet disetujui wajib; batas biaya `global` bulan berjalan wajib (`PUT /ai-budgets`, owner) + per klien opsional; satu job aktif per request; perkiraan biaya job yang masih antre ikut dihitung (dikunci advisory lock) |
| Antrean | `FOR UPDATE SKIP LOCKED` (aman untuk banyak worker); panggilan model di luar transaksi; provider tidak tersedia = coba lagi 30/60 s, maks 3; ditolak model = `refused`; worker mati = job dikembalikan (`worker_timeout` setelah 3), worker lama kehilangan lease dan tidak bisa menyimpan (biayanya tetap dicatat); error tak terduga saat menyimpan = `invalid_output`, job tidak macet; `stop_grace_period` 2 menit saat deploy; request ditutup di tengah jalan = `request_closed` |
| Database (migrasi 0006) | `ai_jobs` (transisi status, beku setelah selesai, tidak dihapus), `ai_calls` append-only (biaya/token, tanpa isi), `ai_budgets`; draft agent untuk klien NYATA hanya dari job yang berjalan (`ai_draft_without_job`) dan minimal L2 (review independen manusia); peminta job = pembuat draft (`qa_reviewer_is_author`, `approval_by_author`) |
| Biaya | `GET /ai-usage` (owner): total, per klien, per agent, status batas + peringatan (`alert_at_pct`). Mikro-USD |
| Jejak | `audit_log`: `ai_job.create/succeeded/failed/retry/reaped/cancel`, `ai_budget.set`; tanpa isi request, fakta, atau hasil |

UI (PR 4d): tombol *Buat draft dengan AI* di `/requests/[id]` dan halaman owner `/ai-usage`. Provider Claude (model per tingkat kesulitan, output terstruktur, caching, fallback refusal) menyusul di PR 4c.

Test: `tests/test_ai.py` (termasuk regresi audit 2026-10-16: alur SIMULASI utuh, contoh "private beach" ditandai dan mengunci approval sampai versi tanpa klaim itu, prompt hanya fakta terbaru yang dikonfirmasi + penyamaran, penjaga endpoint, peran & isolasi klien, retry/tolak/request ditutup/worker mati, dua worker tidak mengambil job yang sama, tombol mati, aturan database 0006, batas biaya) dan `tests/compose_ai_smoke.py` (CI job `docker`: container backend → database → container worker).

## Langganan & Kredit (0.11.0, model langganan)

Sumber aturan: core AI-CONSTITUTION v4.0.0 §4b, AI-BOUNDARY 2.0.0 § Token Kanal & Pembayaran, api-contracts 0.11.0. Harga & tarif: `app/billing/catalog.py` = `clau-market/commercial/pricing.md` (dites `tests/test_billing.py`).

| Bagian | Isi |
|---|---|
| Tabel (migrasi 0008) | `payments` (tagihan; transisi pending → paid/expired/failed, beku setelah selesai), `subscriptions` (paket lunas; perpanjangan dimulai saat paket lama habis), `credit_ledger` (append-only; saldo = jumlah delta per bucket `monthly`/`topup`) |
| Kredit bulanan | 500 per periode bulan langganan, diberikan saat saldo dibaca/dipakai (tanpa cron); sisa periode lalu hangus (`monthly_expire`) |
| Pemakaian | `POST /requests/{id}/ai-drafts` memotong tarif intent (bulanan dulu, lalu top up) di transaksi yang sama dengan job; kurang = 402 `credits_insufficient`. Job `failed`/`cancelled` → refund otomatis (trigger `trg_ai_jobs_refund`). Klien SIMULASI gratis |
| Bayar | `CLAU_PAYMENT_PROVIDER=fake` (mode uji; owner melunasi lewat `simulate-paid`, ditolak bila `CLAU_ENV=production`) atau `midtrans` (Snap; lunas hanya dari webhook `POST /billing/webhooks/midtrans` dengan tanda tangan SHA512 + cek nominal, idempoten). Server key hanya di `.env` server |
| Belum | Pendaftaran klien mandiri (sekarang owner membuat akun & klien), kedaluwarsa kredit top up 12 bulan (tanggal dicatat, belum ditegakkan), posting ke kanal setelah approve (OAuth Meta/TikTok) |

## Belum Ada (Planned)

Provider AI nyata (PR 4c), notifikasi ke klien, Portal Klien terpisah.
