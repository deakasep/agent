// Panggilan API dari browser ke /api/* (diteruskan server Next.js ke backend). Request yang mengubah data
// membawa header CSRF dari /auth/me; error selalu berbentuk kontrak {error: {code, message}}.
export type Membership = { scope: string; role: string; max_level: string };
export type User = {
  id: number;
  display_name: string;
  email: string;
  memberships: Membership[];
  mfa_enabled: boolean;
  disabled: boolean;
  last_login_at: string | null;
};
export type Me = {
  user: User;
  mfa_required: boolean;
  must_change_password: boolean;
  next: "ready" | "password_change" | "mfa_setup";
  active_sessions: number;
  recovery_codes_left: number;
  csrf_token: string;
};
export type ApiResult<T> = { ok: true; data: T } | { ok: false; status: number; code: string; message: string };

let csrf = "";

export async function api<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<ApiResult<T>> {
  const method = init.method ?? "GET";
  const headers: Record<string, string> = { accept: "application/json" };
  if (init.body !== undefined) headers["content-type"] = "application/json";
  if (method !== "GET" && csrf) headers["x-csrf-token"] = csrf;
  let res: Response;
  try {
    res = await fetch(`/api/${path}`, { method, headers, body: init.body === undefined ? undefined : JSON.stringify(init.body), credentials: "same-origin", cache: "no-store" });
  } catch {
    return { ok: false, status: 0, code: "network_error", message: "" };
  }
  const data = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) {
    const err = (data as { error?: { code: string; message: string } } | null)?.error;
    return { ok: false, status: res.status, code: err?.code ?? "http_error", message: err?.message ?? `HTTP ${res.status}` };
  }
  if (data && typeof data === "object" && "csrf_token" in data) csrf = (data as Me).csrf_token;
  return { ok: true, data: data as T };
}

export function roleOf(me: Me): string {
  return me.user.memberships.find((m) => m.scope === "agency")?.role ?? me.user.memberships[0]?.role ?? "";
}

export function isOwner(me: Me): boolean {
  return me.user.memberships.some((m) => m.scope === "agency" && m.role === "owner");
}

/** Tujuan setelah login: hanya path di origin yang sama (cegah open redirect, termasuk /\evil.com dan //evil.com). */
export function safeNext(raw: string | null, origin = typeof window === "undefined" ? "http://localhost" : window.location.origin): string {
  if (!raw || !raw.startsWith("/")) return "/";
  try {
    const url = new URL(raw, origin);
    if (url.origin !== origin || url.pathname.startsWith("/api/")) return "/";
    return url.pathname + url.search + url.hash;
  } catch {
    return "/";
  }
}

// Pesan error dua bahasa per kode kontrak (core/shared/api-contracts.md). Kode lain memakai pesan server.
const MESSAGES: Record<string, [en: string, id: string]> = {
  invalid_credentials: ["Wrong email or password.", "Email atau password salah."],
  too_many_attempts: ["Too many failed attempts. Try again in 15 minutes.", "Terlalu banyak percobaan gagal. Coba lagi dalam 15 menit."],
  mfa_required: ["Enter the 6-digit code from your authenticator app.", "Masukkan kode 6 digit dari aplikasi authenticator."],
  invalid_mfa_code: ["Wrong or already used code. Check that your phone's clock is automatic, then try the next code.", "Kode salah atau sudah dipakai. Pastikan jam HP otomatis, lalu coba kode berikutnya."],
  invalid_recovery_code: ["Wrong or already used backup code.", "Kode cadangan salah atau sudah dipakai."],
  mfa_key_mismatch: ["2FA can't be checked because the server key changed. Ask the server admin to run reset-mfa.", "2FA tidak bisa diperiksa karena kunci server berubah. Minta admin server menjalankan reset-mfa."],
  invalid_current_password: ["Current password is wrong.", "Password saat ini salah."],
  weak_password: ["", ""],
  password_change_required: ["Change your temporary password first.", "Ganti password sementara dulu."],
  mfa_setup_required: ["Turn on 2FA first.", "Aktifkan 2FA dulu."],
  csrf_failed: ["Your session expired on this page. Reload and try again.", "Sesi di halaman ini kedaluwarsa. Muat ulang lalu coba lagi."],
  origin_not_allowed: ["Request blocked: it didn't come from this app.", "Request ditolak: bukan dari aplikasi ini."],
  unauthenticated: ["Please sign in.", "Silakan masuk."],
  forbidden: ["You don't have permission to do this.", "Kamu tidak punya izin untuk melakukan ini."],
  email_taken: ["That email already has an account.", "Email itu sudah punya akun."],
  invalid_membership: ["That role doesn't fit the selected client or agency.", "Peran tidak cocok dengan klien/agency yang dipilih."],
  last_owner: ["There must always be at least one active owner.", "Harus selalu ada minimal satu owner aktif."],
  cannot_disable_self: ["You can't disable your own account.", "Kamu tidak bisa menonaktifkan akunmu sendiri."],
  auth_unavailable: ["Sign-in isn't set up on this server yet.", "Login belum diatur di server ini."],
  database_unavailable: ["The database isn't connected yet.", "Database belum tersambung."],
  backend_unavailable: ["Sign-in isn't active on this server (preview with sample data).", "Login belum aktif di server ini (pratinjau dengan data contoh)."],
  backend_unreachable: ["The server can't be reached. Try again in a moment.", "Server tidak bisa dihubungi. Coba lagi sebentar lagi."],
  network_error: ["No connection. Check your internet and try again.", "Tidak ada koneksi. Periksa internet lalu coba lagi."],
  // Workflow (API 0.7.0, core/shared/api-contracts.md § Kode Aturan Approval).
  not_found: ["Not found, or you don't have access.", "Data tidak ditemukan atau kamu tidak punya akses."],
  unknown_intent: ["Unknown request type.", "Jenis permintaan tidak dikenal."],
  client_not_found: ["Unknown client.", "Klien tidak dikenal."],
  intent_not_active: ["This pillar isn't active yet; escalate to the owner.", "Pilar ini belum aktif; eskalasikan ke owner."],
  claim_fact_key_required: ["Every factual claim needs a fact key from the client's fact sheet.", "Setiap klaim fakta wajib punya fact key dari fact sheet klien."],
  claim_source_required: ["DATA FINAL claims need a source and source date.", "Klaim DATA FINAL wajib punya sumber dan tanggal sumber."],
  draft_client_mismatch: ["That brief or fact sheet doesn't belong to this client.", "Brief atau fact sheet itu bukan milik klien ini."],
  independent_review_not_allowed: ["Only the owner or a content lead can do an independent review.", "Review independen hanya oleh owner atau content lead."],
  level_not_allowed: ["This approval level is above your limit.", "Level approval ini di atas batasmu."],
  facts_unconfirmed: ["Some facts aren't confirmed by the client in an approved fact sheet yet.", "Ada fakta yang belum dikonfirmasi klien di fact sheet yang disetujui."],
  approval_version_mismatch: ["A newer version of this draft exists. Review the latest version.", "Sudah ada versi draft yang lebih baru. Review versi terbaru."],
  approval_level_too_low: ["This content needs a higher approval level.", "Konten ini butuh level approval yang lebih tinggi."],
  approval_by_author: ["You can't decide on something you prepared yourself.", "Kamu tidak bisa memutuskan sesuatu yang kamu susun sendiri."],
  request_closed: ["This request is already finished. Create a new request for changes.", "Request ini sudah selesai. Buat request baru untuk perubahan."],
  approval_role_mismatch: ["Your role doesn't allow approving for this client.", "Peranmu tidak boleh memberi approval untuk klien ini."],
  qa_role_mismatch: ["Your role doesn't allow recording QA.", "Peranmu tidak boleh mencatat QA."],
  invalid_input: ["Some input is invalid. Check it and try again.", "Ada input yang tidak valid. Periksa lalu coba lagi."],
  approval_needs_written_evidence: ["Add the client's written approval (link to the archived email/message).", "Lampirkan bukti persetujuan tertulis klien (link email/pesan yang diarsipkan)."],
  approval_needs_independent_review: ["L2/L3 needs a passed independent claim verification first.", "L2/L3 butuh claim verification independen yang lulus dulu."],
  qa_reviewer_is_author: ["The draft's author can't be its independent reviewer.", "Pembuat draft tidak bisa menjadi reviewer independennya."],
  simulasi_not_approved: ["Simulation content can never be approved.", "Konten SIMULASI tidak pernah bisa disetujui."],
  draft_version_immutable: ["A saved version can't be changed. Save a new version instead.", "Versi yang tersimpan tidak bisa diubah. Simpan sebagai versi baru."],
  decision_record_append_only: ["Recorded decisions and answers can't be changed. Record a new one.", "Keputusan dan jawaban yang tercatat tidak bisa diubah. Catat yang baru."],
  publication_without_approval: ["This draft has no valid approval to mark as published.", "Draft ini belum punya approval yang berlaku untuk ditandai tayang."],
  // Klien & fact sheet (API 0.8.0).
  client_exists: ["That client code is already used.", "Kode klien itu sudah dipakai."],
  fact_sheet_frozen: ["This fact sheet is approved and frozen. Create a new version.", "Fact sheet ini sudah disetujui dan dibekukan. Buat versi baru."],
  fact_not_in_sheet: ["That fact isn't in this version.", "Fakta itu tidak ada di versi ini."],
  fact_value_required: ["A correction needs the right value.", "Koreksi wajib berisi nilai yang benar."],
  fact_value_unchanged: ["The correction is the same as the current value. Choose “Correct” instead.", "Koreksi sama dengan nilai sekarang. Pilih “Benar” saja."],
  fact_sheet_superseded: ["This draft uses an older fact sheet. Save a new version with the latest approved fact sheet.", "Draft ini memakai fact sheet versi lama. Simpan versi baru dengan fact sheet terbaru yang disetujui."],
  ai_disabled: ["AI drafting is switched off by the owner.", "Fitur AI sedang dimatikan owner."],
  ai_intent_not_enabled: ["AI is not enabled for this content type yet.", "AI belum diaktifkan untuk jenis konten ini."],
  fact_sheet_required: ["AI only writes from facts the client approved. Approve a fact sheet first.", "AI hanya menulis dari fakta yang sudah disetujui klien. Setujui fact sheet dulu."],
  ai_provider_test_only: ["AI test mode only works for SIMULATION clients.", "Mode uji AI hanya untuk klien SIMULASI."],
  ai_budget_missing: ["The owner has not set this month's AI budget yet.", "Batas biaya AI bulan ini belum diatur owner."],
  ai_budget_exceeded: ["This month's AI budget has been reached.", "Batas biaya AI bulan ini sudah tercapai."],
  ai_job_active: ["An AI draft for this request is already in progress.", "Draft AI untuk request ini sedang dikerjakan."],
  ai_job_not_cancellable: ["This AI job already started or finished, so it can't be cancelled.", "Job AI sudah berjalan atau selesai, jadi tidak bisa dibatalkan."],
  ai_job_transition: ["This AI job can't change that way.", "Status job AI tidak bisa diubah seperti itu."],
  ai_job_draft_mismatch: ["The AI result doesn't match this request.", "Hasil AI tidak cocok dengan request ini."],
  ai_record_append_only: ["AI records can't be changed or deleted.", "Catatan AI tidak bisa diubah atau dihapus."],
  ai_draft_without_job: ["Agent drafts for real clients only come from an AI job.", "Draft agent untuk klien nyata hanya dari job AI."],
  fact_sheet_empty: ["A fact sheet needs at least one fact.", "Fact sheet butuh minimal satu fakta."],
  fact_sheet_approval_flow: ["Fact sheets can only be approved, not edited. Create a new version.", "Fact sheet hanya bisa disetujui, tidak diubah. Buat versi baru."],
  fact_sheet_version_sequence: ["Someone just saved a version. Reload and try again.", "Baru saja ada versi tersimpan. Muat ulang lalu coba lagi."],
  validation_error: ["Some fields are missing or invalid.", "Ada isian yang kosong atau tidak valid."],
  // Penanda isi konten & level approval otomatis (API 0.10.0, TASK-032).
  content_flags_required: ["Tick what this content contains, or confirm it has none of them.", "Centang isi konten ini, atau nyatakan tidak ada satu pun."],
  review_rating_required: ["Enter the review's star rating (1–5).", "Isi rating bintang review (1–5)."],
  source_draft_required: ["Choose the draft to translate.", "Pilih draft yang akan diterjemahkan."],
  source_draft_invalid: ["That draft wasn't found for this client.", "Draft itu tidak ditemukan untuk klien ini."],
  flag_exists: ["This flag is already on the draft.", "Penanda ini sudah ada di draft."],
  flag_not_removable: ["Flags set automatically by the system can't be removed. Save a corrected new version instead.", "Penanda otomatis dari sistem tidak bisa dihapus. Simpan versi baru yang sudah diperbaiki."],
  flag_not_active: ["This flag is no longer on the draft.", "Penanda ini sudah tidak ada di draft."],
  // Langganan & kredit (API 0.11.0, migrasi 0008).
  credits_insufficient: ["Not enough credits for this job. Top up from Credits & plan.", "Kredit tidak cukup untuk pekerjaan ini. Top up di Kredit & paket."],
  credit_insufficient: ["Not enough credits.", "Kredit tidak cukup."],
  credit_entry_invalid: ["This credit change isn't allowed.", "Perubahan kredit ini tidak diizinkan."],
  credit_cost_missing: ["No credit price is set for this job type yet.", "Tarif kredit untuk jenis pekerjaan ini belum diatur."],
  payment_transition: ["This invoice is already finished.", "Tagihan ini sudah selesai."],
  subscription_payment_mismatch: ["A plan needs a matching paid invoice.", "Paket butuh tagihan lunas yang sesuai."],
  billing_record_append_only: ["Billing records can't be changed or deleted.", "Catatan tagihan & kredit tidak bisa diubah atau dihapus."],
  invalid_plan: ["Choose one of the available plans.", "Pilih paket yang tersedia."],
  payment_pending_exists: ["You still have an unpaid invoice. Pay it or wait until it expires.", "Masih ada tagihan belum dibayar. Bayar atau tunggu kedaluwarsa."],
  billing_disabled: ["Payments are not available right now.", "Pembayaran sedang tidak tersedia."],
  payment_gateway_unavailable: ["The payment gateway can't be reached. Try again.", "Payment gateway tidak bisa dihubungi. Coba lagi."],
  payment_not_pending: ["This invoice is already finished.", "Tagihan ini sudah selesai."],
  billing_simulation_disabled: ["Test payments are not available here.", "Pembayaran uji tidak tersedia di sini."],
};

/** Pesan error sesuai bahasa aktif. weak_password memakai alasan dari server (bahasa Indonesia). */
export function errorText(r: { code: string; message: string }, lang: string): string {
  const pair = MESSAGES[r.code];
  if (!pair || !pair[0]) return r.message || (lang === "id" ? "Terjadi kesalahan." : "Something went wrong.");
  return lang === "id" ? pair[1] : pair[0];
}
