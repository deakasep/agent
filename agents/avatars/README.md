# Avatar 3D Agent

Figur 3D (gaya figurine chibi, latar mint `#DDF4EE`) untuk 15 agent di `registry.json`. Dibuat dengan image generator dari paket prompt CLAU, dikirim owner pada 2026-10-08.

| Lokasi | Isi |
|---|---|
| `agents/avatars/<id>.webp` | Master 1248×832 (seluruh badan) |
| `frontend/public/agents/<id>.webp` | Crop kepala & bahu 256×256, dipakai komponen `Avatar` |

Agent konsep (belum ada di registry) memakai `concept-<nama>.webp`; konsep tanpa gambar jatuh ke karakter SVG (`frontend/components/Character.tsx`). Nova, Aruna, Dara (konsep sejak 2026-10-08) dipromosikan 2026-10-29 menjadi `image-creator`, `video-creator`, `data-analyst` (file di-rename, gambar sama).

Peningkatan kualitas (4K, vinyl mengilap, adegan nyata, pose aksi) tanpa mengganti karakter: [arahan-visual-v2.md](./arahan-visual-v2.md).

## Aturan

- Karakter fiktif; tidak meniru wajah staf atau orang nyata.
- UI tetap menandai bahwa ini agent AI (role "AI …", persona README prinsip 1).
- Batik hanya sebagai pakaian; tanpa simbol sakral (brand-guideline §6–7).
- Nama agent (`display_name`), path avatar, dan jenis figur (`figure`) tercatat di `agents/registry.json` (sumber tunggal, sejak registry 0.3.0); frontend membaca dari sana.
- Ganti gambar = ganti master + crop dengan nama file yang sama (`<id>.webp`).
- Agent baru di `registry.json` wajib punya master + crop; `backend/tests/test_avatars.py` (CI) gagal bila file hilang, bukan WebP, > 150 KB, atau tidak terpakai.

## Status per gambar

Semua gambar v1 disetujui owner Dea Karisna (2026-10-30, sesi Claude). Perintah owner lewat chat = persetujuan; tidak ada langkah persetujuan terpisah.

| Agent | Status | Catatan |
|---|---|---|
| caption-writer, reel-scripter, story-writer, listing-writer, review-responder, calendar-planner, campaign-planner, localizer, sales-assistant | `DATA FINAL` | Diterima di sesi 2026-10-08; disetujui owner Dea Karisna 2026-10-30 |
| report-builder | `DATA FINAL` | Nama ditukar Galih → Intan (2026-10-08) agar sesuai figur; opsional: generate ulang menghadap depan |
| image-creator, video-creator, data-analyst | `DATA FINAL` | Dulu concept-nova/aruna/dara; dipromosikan 2026-10-29 (planned, persona & eval ada) |
| guest-messenger, sop-writer | `DATA FINAL` | Diganti 2026-10-08: layar HP tanpa teks (Sari), proporsi chibi diseragamkan (Teguh) |

Prompt dasar yang dipakai:

```
3D chibi vinyl figurine character, Pixar-style, soft matte clay and fabric materials,
big head small body proportions, large warm brown eyes, gentle closed-mouth smile,
rosy cheeks, Indonesian appearance, full body standing, front view, centered,
plain soft mint background (#DDF4EE) with subtle floor shadow, soft studio lighting,
high detail, clean, friendly, professional. No text, no letters, no logo, no watermark.
```
