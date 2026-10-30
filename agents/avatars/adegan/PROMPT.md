# Prompt adegan v2 — 15 agen CLAU (gaya acuan: Tara di kafe)

**v2.1 (2026-10-31, perintah owner): semua agen pose tegak menghadap lurus ke depan / ke kamera** (sebelumnya pose tiga perempat).

Gaya acuan disetujui owner Dea Karisna 2026-10-30: [`caption-writer.webp`](./caption-writer.webp). Arahan lengkap: [../arahan-visual-v2.md](../arahan-visual-v2.md).

**Cara pakai (per agen):**
1. Buka pembuat gambar yang sama dengan Tara.
2. Unggah gambar lama agen sebagai **referensi karakter**: `agents/avatars/<id>.webp` (kolom "Referensi" di bawah).
3. Tempel prompt agen itu apa adanya. Ukuran: **4K (3840×2160)** bila tersedia, kalau tidak 2048×2048 / 1024×1024 dulu.
4. Cek: wajah, rambut, pakaian, dan benda tugas harus sama dengan referensi; tidak ada teks/logo; wajah orang di latar tidak terlihat jelas.
   Bing Image Creator / Copilot kadang memblokir prompt aman (salah tangkap). Hindari frasa "real people" / "faces" / "human"; kalau masih diblokir, hapus bagian `No text...` di akhir lalu coba lagi.
5. Kirim hasil ke sesi Claude → disimpan sebagai `agents/avatars/adegan/<id>.webp` (≤ 150 KB, master asli di Drive).

Bagian gaya yang sama di semua prompt (jangan diubah, ini yang membuat 15 agen terasa satu tim):
`semi-gloss vinyl with subtle reflections, visible stitching and real fabric texture, small teal leaf-shaped badge on the chest,
natural warm window light, shallow depth of field with softly blurred real interior, desk-toy scale, cinematic color grading,
ultra detailed, 4K. No text, no letters, no logo, no watermark.`

---

### 1. Tara — caption-writer · Referensi: `caption-writer.webp`
```
Realistic photo of a small 3D vinyl toy figurine (the SAME character as the reference image: same face, black hair with bangs, mint jacket, brown batik skirt, orange pencil and smartphone), standing on a wooden café table next to an iced coffee latte and an open laptop, holding the phone and pencil as if writing a caption, standing upright in a front-facing pose, facing straight forward toward the camera, looking directly at the camera, semi-gloss vinyl with subtle reflections, visible stitching and real batik fabric texture, small teal leaf-shaped badge on the chest, natural late-afternoon window light, shallow depth of field with softly blurred real café interior, desk-toy scale, cinematic color grading, ultra detailed, 4K. No text, no letters, no logo, no watermark.
```

### 2. Raka — reel-scripter · Referensi: `reel-scripter.webp`
```
Realistic photo of a small 3D vinyl toy figurine (the SAME character as the reference image: same face, wavy black hair, teal batik shirt, khaki pants, white sneakers), standing on a wooden table of a beach-side villa terrace at golden hour with the sea softly blurred behind, holding a small phone gimbal while filming, a tiny film clapperboard beside his feet, standing upright in a front-facing pose, facing straight forward toward the camera, looking directly at the camera, semi-gloss vinyl with subtle reflections, visible stitching and real batik fabric texture, small teal leaf-shaped badge on the chest, warm golden-hour sunlight with rim light, shallow depth of field, desk-toy scale, cinematic color grading, ultra detailed, 4K. No text, no letters, no logo, no watermark.
```

### 3. Sekar — story-writer · Referensi: `story-writer.webp`
```
Realistic photo of a small 3D vinyl toy figurine (the SAME character as the reference image: same face, soft pink hijab, long cream coat, smartphone with colorful story bars), standing on a wooden windowsill of a Bali villa bedroom with carved wooden window frames and tropical plants softly blurred outside, holding the phone up vertically as if recording a story, a few tiny emoji-style stickers (heart, star) on the sill, standing upright in a front-facing pose, facing straight forward toward the camera, looking directly at the camera, semi-gloss vinyl with subtle reflections, visible stitching and real fabric texture, small teal leaf-shaped badge on the chest, natural morning window light, shallow depth of field, desk-toy scale, cinematic color grading, ultra detailed, 4K. No text, no letters, no logo, no watermark.
```

### 4. Bayu — listing-writer · Referensi: `listing-writer.webp`
```
Realistic photo of a small 3D vinyl toy figurine (the SAME character as the reference image: same face, black hair, round glasses, navy vest over white shirt, black trousers, framed villa photo), standing on a teak side table on a villa terrace beside a turquoise swimming pool softly blurred behind, proudly holding the framed villa photo, a tiny wooden room key tag next to his feet, standing upright in a front-facing pose, facing straight forward toward the camera, looking directly at the camera, semi-gloss vinyl with subtle reflections, visible stitching and real fabric texture, small teal leaf-shaped badge on the chest, bright late-morning tropical light, shallow depth of field, desk-toy scale, cinematic color grading, ultra detailed, 4K. No text, no letters, no logo, no watermark.
```

### 5. Laras — review-responder · Referensi: `review-responder.webp`
```
Realistic photo of a small 3D vinyl toy figurine (the SAME character as the reference image: same face, brown hair in a low bun, teal blazer with small gold pin, white shirt, black skirt, speech bubble with a red heart), standing on a polished wooden hotel reception desk with a softly blurred elegant lobby behind, holding up the heart speech bubble warmly, three tiny gold stars floating near the bubble, standing upright in a front-facing pose, facing straight forward toward the camera, looking directly at the camera, semi-gloss vinyl with subtle reflections, visible stitching and real fabric texture, small teal leaf-shaped badge on the chest, warm lobby lighting with soft window light, shallow depth of field, desk-toy scale, cinematic color grading, ultra detailed, 4K. No text, no letters, no logo, no watermark.
```

### 6. Dimas — calendar-planner · Referensi: `calendar-planner.webp`
```
Realistic photo of a small 3D vinyl toy figurine (the SAME character as the reference image: same face, short black hair, pencil tucked behind the ear, mint polo shirt, khaki trousers, white desk calendar with colorful dots), standing on a wooden work desk in front of a softly blurred cork board covered with colorful sticky notes, placing a colorful dot sticker on the calendar, standing upright in a front-facing pose, facing straight forward toward the camera, looking directly at the camera, semi-gloss vinyl with subtle reflections, visible stitching and real fabric texture, small teal leaf-shaped badge on the chest, natural warm window light, shallow depth of field, desk-toy scale, cinematic color grading, ultra detailed, 4K. No text, no letters, no logo, no watermark.
```

### 7. Ayu — campaign-planner · Referensi: `campaign-planner.webp`
```
Realistic photo of a small 3D vinyl toy figurine (the SAME character as the reference image: same face, brown bob hair with bangs, rust-orange blazer, cream top, black trousers, small megaphone and a rolled plan), standing on a meeting room table with a softly blurred whiteboard full of colorful diagrams behind, raising the megaphone energetically while holding the rolled plan, standing upright in a front-facing pose, facing straight forward toward the camera, looking directly at the camera, semi-gloss vinyl with subtle reflections, visible stitching and real fabric texture, small teal leaf-shaped badge on the chest, bright natural office light, shallow depth of field, desk-toy scale, cinematic color grading, ultra detailed, 4K. No text, no letters, no logo, no watermark.
```

### 8. Nara — localizer · Referensi: `localizer.webp`
```
Realistic photo of a small 3D vinyl toy figurine (the SAME character as the reference image: same face, curly black hair, round glasses, light blue sweater with white collar, khaki trousers, small globe and two blank speech bubbles), standing on a wooden table in a boutique hotel lobby with a large vintage world map softly blurred on the wall behind, holding the globe with two blank speech bubbles floating beside him, standing upright in a front-facing pose, facing straight forward toward the camera, looking directly at the camera, semi-gloss vinyl with subtle reflections, visible stitching and real knit texture, small teal leaf-shaped badge on the chest, warm natural window light, shallow depth of field, desk-toy scale, cinematic color grading, ultra detailed, 4K. No text, no letters, no logo, no watermark.
```

### 9. Nova — image-creator · Referensi: `image-creator.webp`
```
Realistic photo of a small 3D vinyl toy figurine (the SAME character as the reference image: same face, shoulder-length brown hair, round glasses, navy blazer, cream turtleneck, beige trousers, white sneakers, color palette board), standing on a white tabletop in a small photo studio with a softly blurred softbox light and backdrop behind, holding up the color palette board next to a tiny empty picture frame, standing upright in a front-facing pose, facing straight forward toward the camera, looking directly at the camera, semi-gloss vinyl with subtle reflections, visible stitching and real fabric texture, small teal leaf-shaped badge on the chest, soft studio key light with warm rim light, shallow depth of field, desk-toy scale, cinematic color grading, ultra detailed, 4K. No text, no letters, no logo, no watermark.
```

### 10. Aruna — video-creator · Referensi: `video-creator.webp`
```
Realistic photo of a small 3D vinyl toy figurine (the SAME character as the reference image: same face, long black hair, dark green beret, olive utility vest, jeans, brown boots, small camera), standing on a wooden table on a mini film set with a softly blurred small LED panel light and tripod behind, holding the small camera at chest height ready to film, a tiny LED light beside her, standing upright in a front-facing pose, facing straight forward toward the camera, looking directly at the camera, semi-gloss vinyl with subtle reflections, visible stitching and real fabric texture, small teal leaf-shaped badge on the chest, moody warm set lighting with rim light, shallow depth of field, desk-toy scale, cinematic color grading, ultra detailed, 4K. No text, no letters, no logo, no watermark.
```

### 11. Intan — report-builder · Referensi: `report-builder.webp`
```
Realistic photo of a small 3D vinyl toy figurine (the SAME character as the reference image: same face, long black hair in a ponytail, large round glasses, navy blazer, grey trousers, tablet showing a simple bar chart), standing on a tidy wooden office desk in front of a softly blurred monitor displaying colorful charts, presenting the tablet chart, standing upright in a front-facing pose, facing straight forward toward the camera, looking directly at the camera, semi-gloss vinyl with subtle reflections, visible stitching and real fabric texture, small teal leaf-shaped badge on the chest, natural daylight from a side window, shallow depth of field, desk-toy scale, cinematic color grading, ultra detailed, 4K. No text, no letters, no logo, no watermark.
```

### 12. Dara — data-analyst · Referensi: `data-analyst.webp`
```
Realistic photo of a small 3D vinyl toy figurine (the SAME character as the reference image: same face, dark hair with a side braid, purple blazer, dark trousers, magnifying glass and clipboard with a chart), standing on a desk in a modern data room with several softly blurred dashboard screens glowing behind, inspecting the clipboard chart through the magnifying glass, standing upright in a front-facing pose, facing straight forward toward the camera, looking directly at the camera, semi-gloss vinyl with subtle reflections, visible stitching and real fabric texture, small teal leaf-shaped badge on the chest, cool screen glow mixed with warm desk lamp light, shallow depth of field, desk-toy scale, cinematic color grading, ultra detailed, 4K. No text, no letters, no logo, no watermark.
```

### 13. Galih — sales-assistant · Referensi: `sales-assistant.webp`
```
Realistic photo of a small 3D vinyl toy figurine (the SAME character as the reference image: same face, short black hair, dark teal suit, brown notebook and smartphone), standing on a hotel front office counter beside a small stack of blank travel brochures, with a softly blurred hotel entrance behind, holding the notebook and phone with a confident friendly smile, standing upright in a front-facing pose, facing straight forward toward the camera, looking directly at the camera, semi-gloss vinyl with subtle reflections, visible stitching and real wool suit texture, small teal leaf-shaped badge on the chest, warm natural light, shallow depth of field, desk-toy scale, cinematic color grading, ultra detailed, 4K. No text, no letters, no logo, no watermark.
```

### 14. Sari — guest-messenger · Referensi: `guest-messenger.webp`
```
Realistic photo of a small 3D vinyl toy figurine (the SAME character as the reference image: same face, mint hijab, mint vest over cream shirt, brown trousers, smartphone with a blank screen), standing on a wooden concierge desk of a Bali villa next to a small brass hotel bell and a frangipani flower, holding the phone as if replying to a guest, standing upright in a front-facing pose, facing straight forward toward the camera, looking directly at the camera, semi-gloss vinyl with subtle reflections, visible stitching and real fabric texture, small teal leaf-shaped badge on the chest, natural late-afternoon window light, shallow depth of field with softly blurred villa lobby, desk-toy scale, cinematic color grading, ultra detailed, 4K. No text, no letters, no logo, no watermark.
```

### 15. Teguh — sop-writer · Referensi: `sop-writer.webp`
```
Realistic photo of a small 3D vinyl toy figurine (the SAME character as the reference image: same face, black hair with grey sides, purple polo shirt, grey trousers, clipboard with a checklist of ticks), standing on a wooden table in a tidy hotel back office with softly blurred shelves of neatly labeled binders behind (labels blank), ticking the checklist with a small pen, standing upright in a front-facing pose, facing straight forward toward the camera, looking directly at the camera, semi-gloss vinyl with subtle reflections, visible stitching and real fabric texture, small teal leaf-shaped badge on the chest, calm natural window light, shallow depth of field, desk-toy scale, cinematic color grading, ultra detailed, 4K. No text, no letters, no logo, no watermark.
```

---

### Bonus — gambar tim untuk halaman utama situs (setelah semua agen jadi)
Unggah 3–4 gambar adegan agen sebagai referensi.
```
Photorealistic photo of four small 3D vinyl collectible figurines (the SAME characters as the reference images) together on a wooden reception desk of a Bali villa: the hijab concierge figurine hands a small room key to the glasses figurine holding a framed villa photo, the figurine with a heart speech bubble waves, the batik-skirt figurine writes on her phone; a laptop at the right edge, small brass hotel bell and frangipani flower, natural late-afternoon window light, shallow depth of field, semi-gloss vinyl with subtle reflections, desk-toy scale, cinematic color grading, ultra detailed, 4K, 3840x2160 wide. No text, no letters, no logo, no watermark.
```
