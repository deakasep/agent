# AGENTS.md — clau-agent

Instruksi untuk ChatGPT/OpenAI Codex, Claude Code, dan AI coding agent lain.

## Baca sebelum bekerja

1. [Status & handoff](https://github.com/deakasep/content/blob/main/docs/status.md).
2. [Instruksi bersama](./core/AGENTS.md), [Constitution](./core/AI-CONSTITUTION.md),
   dan [Boundary](./core/AI-BOUNDARY.md).
3. [Peta platform dan command](./CLAUDE.md), lalu dokumentasi area yang diubah.

Jika submodule belum ada, jalankan `git submodule update --init --recursive`.
File dalam `core/` hanya submodule: ubah aturan di repo sumber clau-core.

## Penyelesaian coding task

Atas perintah Pak Indra 2026-10-27, ChatGPT/Codex dan Claude mengikuti alur yang sama:
feature branch → validasi lokal + self-review → PR → CI hijau → merge → cek main →
sync downstream. **Tidak perlu konfirmasi merge ulang** untuk scope task yang sudah
diizinkan. Gate authoritative ada di core AI-BOUNDARY § Merge oleh AI Coding Agent.

Check wajib platform: `backend`, `frontend`, `audit`, `docker`, `cross-validate`.
Periksa semua run GitHub Actions pada head terbaru, termasuk push dan pull_request;
merge memakai expected head SHA. Jangan bypass ruleset/review, force merge, atau
push langsung ke main. PR dependency di luar scope tidak otomatis ikut di-merge.

Laporan final harus sesuai hasil GitHub yang dibaca langsung: merged, CI main,
dan status sync ke clau-market. CI pending/gagal tidak boleh disebut selesai.
Instruksi ini tidak menjalankan ChatGPT di background setelah sesi berakhir.

Izin merge repo tidak memberikan approval konten client atau izin publish/send.
Data client nyata, credential dan prompt private tidak boleh masuk repo/log.
Aturan human independent review dan batas provider tetap mengikuti core.
