# Komponen Claude dari pihak luar (vendored) — daftar & aturan keamanan

Semua di bawah ini **buatan Anthropic**, lisensi Apache-2.0 (`.claude/vendor/LICENSE-anthropic-apache-2.0.txt`), disalin apa adanya
dan **dikunci ke commit yang sudah direview**. Tidak ada hook, MCP server, skrip, atau koneksi ke layanan luar.

| File | Sumber | Commit (review 2026-10-30) | Catatan keamanan |
|---|---|---|---|
| `.claude/commands/code-review.md` | anthropics/claude-plugins-official `plugins/code-review` | f8c5e7a | Hanya baca diff PR (gh). Komentar ke PR **hanya** jika dipanggil dengan `--comment`. |
| `.claude/commands/review-pr.md` + `.claude/agents/{code-reviewer,code-simplifier,comment-analyzer,pr-test-analyzer,silent-failure-hunter,type-design-analyzer}.md` | anthropics/claude-plugins-official `plugins/pr-review-toolkit` | f8c5e7a | Instruksi agen pemeriksa (Read/Grep/Bash lokal). |
Dipakai: `/review-pr` sebelum membuka PR (wajib untuk perubahan uang/keamanan), `/code-review <PR>` untuk review PR.

## Aturan menambah/menaikkan komponen pihak luar (skill `cari-skill-aman`)
1. Utamakan buatan Anthropic yang tidak tersambung ke layanan luar; pihak ketiga hanya dengan persetujuan pemilik.
2. Baca seluruh isi; tolak hook yang berjalan otomatis, skrip berjaringan, akses token/kredensial, instruksi tersembunyi.
3. Salin per proyek (bukan global), catat sumber + commit di tabel ini, sertakan lisensi.
4. Naik versi = review diff antar-commit dulu. Tidak pernah `npx skills add -g -y`.
5. Ditolak 2026-10-30: `security-guidance` (memanggil API Anthropic dengan kunci API di setiap edit), skill pihak ketiga
   (find-skills, Trail of Bits, review-council), sambungan MCP bawaan plugin knowledge-work (Slack, Gmail, HubSpot, dll.).
6. Pemindai keamanan mendalam `claude-security` (Anthropic, commit f8c5e7a direview: hook hanya banner/hitungan/saran lokal) dipakai
   **sesuai kebutuhan** lewat marketplace resmi saat audit, tidak dipasang permanen di repo karena tidak bisa dikunci ke commit.
