# Arahan Visual v2 — figur agen CLAU sekelas Sintra (tetap karakter CLAU)

Status: `ASSUMPTION` — usulan 2026-10-30 atas permintaan owner, menunggu konfirmasi Pak Indra / Dea Karisna. Karakter v1 (15 figur di folder
ini) **dipertahankan**: wajah, rambut, pakaian, dan benda tugas sama. Yang dinaikkan hanya kualitas render, pencahayaan, pose, dan adegan.
Jangan meniru desain milik Sintra (helm/baju astronot, nama, logo); yang ditiru hanya tingkat kualitas dan konsep "figur mainan + foto nyata".

## 1. Kenapa v1 terasa kurang detail (dibanding sintra.ai, dilihat 2026-10-30)

| Aspek | Sintra | CLAU v1 | Arah v2 |
|---|---|---|---|
| Bahan | vinyl mengilap: pantulan cahaya, garis sambungan, cat detail | clay doff, rata | **vinyl semi-gloss** + bagian kain bertekstur (batik, rajut), jahitan, kancing, logo kecil di badge |
| Cahaya | cahaya jendela/lampu nyata, bayangan lembut, kilap di mata | lampu studio rata | **cahaya alami dari samping + rim light**, kilap di mata & rambut |
| Latar | ruang nyata (ruang kerja, gudang, villa), latar blur (depth of field) | mint polos | **adegan nyata Indonesia** sesuai tugas, latar blur; versi studio tetap ada untuk UI |
| Pose | beraksi & berinteraksi (menyerahkan kotak, melambai) | berdiri tegak menghadap depan | **pose aksi 3/4**, sedang mengerjakan tugasnya, kadang berinteraksi dengan agen lain |
| Resolusi | besar, tajam | 1248×832, file ±30 KB | **master 3840×2160 (4K)** atau lebih, disimpan di luar repo |
| Cerita | benda kecil menceritakan tugas | sudah ada benda tugas | benda tugas diperbanyak & diperjelas (lihat §3) |

## 2. Ciri keluarga CLAU (pengganti "astronot" — milik kita sendiri)
Supaya 15 agen terasa satu tim seperti Sintra:
- **Kartu nama (name badge) kecil** berbentuk daun warna teal `#0F766E` di dada kiri, tanpa teks terbaca.
- **Aksen warna per pilar**: AI Marketing = teal; agen hospitality (Sari, Teguh) = emas lembut; analitik (Intan, Dara) = ungu.
- **Detail Indonesia halus**: kain batik/tenun sebagai pakaian saja (tanpa simbol sakral, brand-guideline §6–7), sandal/sepatu kulit, tas anyaman.
- Proporsi chibi tetap: kepala besar, mata cokelat besar dengan dua titik kilap.

## 3. Adegan per agen (untuk kartu agen & halaman situs)

| Agen | Tugas | Adegan v2 (latar nyata, blur) | Benda tugas |
|---|---|---|---|
| Tara (caption-writer) | caption | meja kafe kayu, kopi susu, laptop terbuka | HP + pensil, kartu caption |
| Raka (reel-scripter) | naskah reel | pantai/villa saat golden hour | gimbal + HP, papan clapper mini |
| Sekar (story-writer) | story | sudut kamar villa dengan jendela kayu | HP vertikal, stiker emoji kecil |
| Bayu (listing-writer) | listing properti | teras villa dengan kolam renang | foto villa berbingkai, kunci kamar |
| Laras (review-responder) | balas ulasan | meja resepsionis hotel | gelembung chat hati, bintang kecil |
| Dimas (calendar-planner) | kalender konten | papan kerja dengan sticky note | kalender dinding bertitik warna |
| Ayu (campaign-planner) | kampanye | ruang rapat kecil, papan tulis | megafon, gulungan rencana |
| Nara (localizer) | terjemahan | lobi hotel dengan peta dunia | globe, dua gelembung bahasa |
| Nova (image-creator) | gambar | studio foto mini, softbox | palet warna, bingkai foto |
| Aruna (video-creator) | video | set syuting mini | kamera, lampu LED kecil |
| Intan (report-builder) | laporan | meja kerja dengan monitor grafik | tablet grafik batang |
| Dara (data-analyst) | analisis | ruang data dengan layar dashboard | kaca pembesar, papan klip grafik |
| Galih (sales-assistant) | penjualan | meja front office, brosur paket | buku catatan, HP |
| Sari (guest-messenger) | pesan tamu | meja concierge dengan bel | HP (layar tanpa teks), bel hotel |
| Teguh (sop-writer) | SOP | ruang staf / back office | papan klip checklist |

## 4. Prompt (pakai gambar v1 sebagai **referensi wajah/karakter** agar identitas tidak berubah)

**A. Master studio 4K (untuk UI, pengganti v1):**
```
3D collectible vinyl figurine of the SAME character as the reference image (keep face, hair, outfit, props identical),
chibi proportions, semi-gloss vinyl with subtle specular highlights, fabric parts with real texture (batik weave, knit),
visible stitching and buttons, small teal leaf-shaped name badge on the chest (no readable text),
dynamic three-quarter pose while doing <TUGAS>, holding <BENDA TUGAS>,
large warm brown eyes with two catchlights, soft rim light and window light from the left, soft contact shadow,
plain soft mint background (#DDF4EE), product photography, 85mm lens, ultra detailed, 4K, 3840x2160.
No text, no letters, no logo, no watermark.
```

**B. Adegan nyata (hero & kartu agen, seperti foto Sintra):**
```
Photorealistic photo of a small 3D vinyl collectible figurine (the SAME character as the reference image) standing on
<PERMUKAAN, mis. a wooden reception desk of a Bali villa>, <ADEGAN dari §3>, natural late-afternoon window light,
shallow depth of field with softly blurred real interior background, realistic reflections on the vinyl,
figurine scale like a desk toy (about 15 cm), cinematic color grading, ultra detailed, 4K, 3840x2160.
No text, no letters, no logo, no watermark, no real people's faces.
```

**C. Tim (gambar utama situs):** sama seperti B, berisi 3–4 agen berinteraksi di satu meja hospitality (mis. Sari menyerahkan kunci kamar ke
Bayu, Laras membawa gelembung hati), tangan manusia boleh tampak sebagian dari samping (tanpa wajah).

## 5. Aturan teknis & persetujuan
- Master 4K disimpan di Client Workspace (Drive), **bukan di repo** (`test_avatars.py` membatasi file avatar ≤ 150 KB).
- Repo hanya menyimpan turunan web: `agents/avatars/<id>.webp` & crop `frontend/public/agents/<id>.webp` (nama sama, ≤ 150 KB), dan gambar
  hero/adegan dalam AVIF/WebP beberapa ukuran (mis. 640/1280/1920/3840) untuk `srcset`, supaya cepat di HP.
- Animasi di situs (repo web, library `motion`): satu momen pembuka (figur muncul bergantian) + kartu agen bergerak saat disentuh;
  hormati `prefers-reduced-motion` (skill `frontend-design`).
- Karakter tetap fiktif, tidak meniru orang nyata; UI tetap menandai "AI …". Gambar baru = status `ASSUMPTION` sampai Pak Indra / Dea Karisna setuju.
