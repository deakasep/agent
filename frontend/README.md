# Frontend (Next.js) — UI v2 Enterprise

Platform **CLAU AI** (modul aktif: Content Studio; tampilan v2) mengikuti [`docs/design/2026-10-07-enterprise-ui-brief.txt`](../docs/design/2026-10-07-enterprise-ui-brief.txt). Login (`/login`, `/account`, `/users`, `/requests`, `/fact-sheets`, `/ai-usage`) aktif bila `CLAU_AUTH_ENABLED=1` dan `CLAU_BACKEND_URL` terisi (docker compose / VPS 2); di VPS 1 (tanpa backend) halaman itu menampilkan "login belum aktif" dan data tetap contoh SIMULASI. AI menulis draft memakai antrean backend (Tahap 2); saat ini provider tiruan untuk klien SIMULASI, provider Claude menyusul.

## Versi UI

| Versi | Branch | Ringkasan |
|---|---|---|
| v1 "Pasir" | `ui-v1-pasir` | Palet brand CLAU: Pasir ±60% latar, Arang ±20% teks, Teal Laut ±10% aksen, Terracotta 3–5% highlight. Karakter ilustrasi per agent. **Disimpan** atas permintaan Dea Karisna (2026-10-07) |
| v2 "Enterprise" | `ui-v2-enterprise` (snapshot tersimpan) · `main` (live di VPS 1 sejak 2026-10-07) |
| v3 "AI Workforce" | `ui-v3-workforce` (snapshot tersimpan) · `main` (live di VPS 1 sejak 2026-10-08) | My AI Team, avatar persona, EN/ID, dark mode. Lihat [`docs/design/2026-10-07-ai-workforce-brief-v2.md`](../docs/design/2026-10-07-ai-workforce-brief-v2.md) | Navy + Deep Teal + putih + slate, sidebar, dashboard SaaS; agent pakai avatar figur 3D (sejak 2026-10-08, brand-guideline §3d) |

### Snapshot palet v2 (disimpan atas permintaan Dea Karisna, 2026-10-07)

| Item | Nilai |
|---|---|
| Nama produk | CLAU AI (merek payung); modul aktif: Content Studio = AI Marketing |
| Aksi utama & aksen | Deep Teal `#0F766E` (hover `#115E59`, muda `#CCFBF1`) · ± 5–10% |
| Sidebar & teks utama | Deep Navy `#0F172A` (sekunder `#1E3A5F`) · ± 15–20% |
| Latar & permukaan | Slate 50 `#F8FAFC` + putih `#FFFFFF` · ± 70–80% |
| Teks sekunder / muted | `#475569` / `#64748B` (`#94A3B8` hanya non-teks) |
| Garis | `#E2E8F0` |
| Status | Success `#16A34A` · Warning `#D97706` · Error `#DC2626` · Info `#2563EB` (selalu dengan label) |
| Font | Inter |
| Sumber token | `clau-content/design/tokens/tokens.json` v1.1.0 `semantic.app-v2` (branch snapshot `tokens-v1.1.0-app-v2`) |

### Snapshot v3 "AI Workforce" (disimpan atas permintaan Dea Karisna, 2026-10-08)

| Item | Nilai |
|---|---|
| Nama | CLAU AI · Content Studio |
| Konsep | "Meet your AI team": agent tampil sebagai karyawan digital. Sejak 2026-10-08 avatar = figur 3D per agent (`public/agents/<id>.webp`, master di [`agents/avatars/`](../agents/avatars/README.md)); agent konsep (Nova, Aruna, Dara) memakai `public/agents/concept-<nama>.webp` |
| Bahasa | English default, toggle **EN / ID** tanpa bendera (`lib/i18n.tsx`, disimpan di `localStorage` `clau-lang`) |
| Tema | Light / Dark / System (`lib/theme.tsx`, `localStorage` `clau-theme`, tanpa kedipan saat load) |
| Light | Navy `#0F172A` sidebar & teks · Teal `#0F766E` aksi · Mint `#CCFBF1` · latar `#F8FAFC` · muted `#64748B` |
| Dark | Latar `#0B1120` · permukaan `#111827` · teks `#F1F5F9` / `#CBD5E1` / `#94A3B8` · aksen teks teal `#5EEAD4` · tombol tetap `#0F766E` |
| Aksen agent | Satu nada per agent: Tara `#0F766E`, Raka `#0E7490`, Sekar `#0369A1`, Bayu `#1E3A5F`, Laras `#4338CA`, Dimas `#047857`, Ayu `#6D28D9`, Nara `#0D9488`, Intan `#155E75`; belum aktif `#64748B` |
| Status | Success `#16A34A` · Warning `#D97706` · Error `#DC2626` · Info `#2563EB` (selalu dengan label) |
| Brief | [`docs/design/2026-10-07-ai-workforce-brief-v2.md`](../docs/design/2026-10-07-ai-workforce-brief-v2.md) |

## Halaman

| Route | Isi |
|---|---|
| `/` | Dashboard: KPI, proyek, perlu tindakan, aktivitas agent, jadwal tayang |
| `/clients`, `/clients/<id>` | Daftar klien & profil (info bisnis, brand voice, akun sosial, riwayat konten) |
| `/projects` | Proyek per klien dengan progres |
| `/content` | Tab status (Draft → Tayang), tabel konten, modal **Buat konten** (tombol generate nonaktif sampai backend AI ada) |
| `/calendar` | Kalender bulan dengan status semantik |
| `/agents`, `/agents/<id>` | Kartu agent (avatar 3D, status, level) & profil dari `../agents/personas/<id>.md` |
| `/workflows` | Alur brief → agent → cek otomatis → review manusia → publish oleh manusia |
| `/reports` | Produksi konten; engagement **tidak** ditampilkan sampai data platform asli tersedia |
| `/settings` | Workspace & integrasi (read-only) |
| `/login` | Masuk: password → kode 2FA atau kode cadangan |
| `/account` | Akun: ganti password, aktifkan 2FA (QR), kode cadangan, sesi aktif & keluar semua perangkat |
| `/users` | Owner: buat user, ubah peran/klien, nonaktifkan/aktifkan; tambah klien |
| `/requests` · `/requests/[id]` | Permintaan konten: buat permintaan, tulis draft per versi (klaim + fact key), **Buat draft dengan AI** (status job diperbarui tiap 3 detik, batalkan selama antre; draft AI diberi tanda, klaim `RISK` disorot; peminta draft AI tidak diberi form review independen/keputusan), catat review QA, catat keputusan klien (bukti tertulis bila dicatat agency). Tidak ada tombol publish |
| `/ai-usage` | Owner: biaya AI per bulan (WITA), per klien & per agent, batas global (wajib) & per klien dengan peringatan |
| `/fact-sheets` · `/fact-sheets/[id]` | Fact sheet per klien: susun versi + daftar fakta, klien menjawab *Benar* / *Perbaiki* per fakta, lalu menyetujui versi itu |

## Data

- `lib/team.ts`: nama, peran, fokus agent (registry tetap sumber daftar agent).
- `lib/demo.ts`: **DATA SIMULASI**. Nama properti fiktif mengandung "Contoh"; setiap halaman yang memakainya menampilkan label SIMULASI.

## Design system

- Token warna di `app/globals.css` (`:root`, brief §31). Ganti tema cukup di sana.
- Font Inter. Ikon garis gaya Lucide di `components/Icon.tsx` (tanpa dependency tambahan).
- Status: warna semantik + label teks (tidak mengandalkan warna saja).

## Jalankan

```bash
npm ci
npm run dev        # http://localhost:3000
npm run build
```

## Keputusan (Dea Karisna, 2026-10-07) — `DATA FINAL`

- Nama produk: **CLAU AI** (wordmark "CLAU AI" + deskriptor modul "Content Studio"; opsi B, keputusan owner 2026-10-09, clau-content#46).
- Palet UI produk v2: navy + deep teal + putih + slate (token di `app/globals.css`). Dicatat di `clau-content/design/brand/brand-guideline.md` §3b.
- Nama agent (Tara, Raka, Sekar, Bayu, Laras, Dimas, Ayu, Nara, Intan, Galih, Sari, Teguh; Nova, Aruna, Dara sejak 2026-10-29) disetujui. Sumber nama: `agents/registry.json` (`display_name`). 2026-10-08: nama report-builder dan sales-assistant ditukar (Intan ↔ Galih) agar sesuai figur 3D.

## Batas

UI tidak boleh punya tombol yang langsung publish ke platform sosial/OTA atau mengirim pesan ke tamu (`core/AI-CONSTITUTION.md` §4).
