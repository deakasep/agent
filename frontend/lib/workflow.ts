// Tipe & helper workflow (kontrak core/shared/api-contracts.md 0.7.0–0.10.0). Aturan di sini hanya untuk
// menampilkan tombol yang relevan; keputusan sebenarnya selalu dicek backend dan database (rule 08).
import { useEffect, useState } from "react";
import { api, type Me, type Membership } from "./auth";

export type Page<T> = { items: T[]; total: number; limit: number; offset: number };
export type Client = { client_code: string; vertical: string; business_type: string; location_area: string | null; approver_role: string; simulation: boolean; self_serve?: boolean };
export type WfRequest = {
  id: number; client_code: string; intent: string; pillar: number; agent: string | null; approval_min: string; text: string;
  deadline: string | null; impact: number; risk: number; priority: string; priority_score: number; status: string;
  requested_by: number | null; requested_by_role: string; created_at: string;
  review_rating?: number | null; source_draft_id?: number | null;
};
export type Claim = { id?: number; text: string; category: string; evidence_label: string; source?: string | null; source_date?: string | null; implied?: boolean; fact_key?: string | null };
export type DraftSummary = {
  id: number; request_id: number; client_code: string; brief_id: string | null; fact_sheet_id: number | null; skill: string;
  version: number; mode: "NYATA" | "SIMULASI"; created_by: number | null; agent_id: string | null; created_at: string; latest: boolean;
};
export type DraftFlag = { flag: ContentFlag; source: "author" | "server" | "staff" | "qa"; added_by: number | null; added_at: string; removed_by: number | null; removed_at: string | null; removed_reason: string | null };
export type Draft = DraftSummary & {
  content: string; claims: Claim[];
  // API 0.10.0: penanda aktif + level minimum dari database (alasan = aturan yang menaikkan level di atas L1).
  content_flags?: DraftFlag[]; min_level?: string; min_level_reasons?: { rule: string; level: string }[];
};
export type QARecord = { id: number; draft_id: number; gate: string; result: string; reviewer_id: number | null; reviewer_role: string; independent: boolean; created_at: string };
export type Approval = { id: number; draft_id: number; level: string; decision: string; approver_id: number; approver_role: string; channel_ref: string | null; mode: string; decided_at: string };
export type FactAnswer = {
  id: number; fact_sheet_id: number; fact_key: string; decision: "confirmed" | "corrected"; value_before: string | null; value_after: string | null;
  confirmed_by: number; confirmed_by_role: string | null; channel_ref: string | null; confirmed_at: string;
};
export type FactSheet = {
  id: number; client_code: string; version: number; document_ref: string; created_by: number | null; created_at: string;
  approved_at: string | null; approved_by: number | null; approved_by_role: string | null; approval_ref: string | null;
  status: "pending" | "ready" | "approved"; facts_total: number; facts_answered: number;
};
export type Fact = { fact_key: string; category: string; label: string; value: string; status: "pending" | "confirmed" | "corrected"; current_value: string; answers: FactAnswer[] };
export type FactSheetDetail = FactSheet & { facts: Fact[] };
export type Agent = { id: string; display_name: string; intents: string[]; status: string; approval_min: string; pillar: number };

export const LEVELS = ["L1", "L2", "L3"] as const;
// Penanda isi konten (kontrak core 0.10.0 § Penanda Isi Konten; Rule 08). Level di sini hanya untuk tampilan.
export const CONTENT_FLAGS = ["price_promo", "people", "ota_listing", "negative_review", "paid_ads", "influencer", "religion_culture", "crisis"] as const;
export type ContentFlag = (typeof CONTENT_FLAGS)[number];
export const FLAG_LEVEL: Record<ContentFlag, string> = {
  price_promo: "L2", people: "L2", ota_listing: "L2", negative_review: "L3", paid_ads: "L3", influencer: "L3", religion_culture: "L3", crisis: "L3",
};
export const FLAG_LABEL: Record<ContentFlag, [string, string]> = {
  price_promo: ["Price, discount or promo", "Harga, diskon, atau promo"],
  people: ["Identifiable people (guests, staff, couples)", "Orang yang bisa dikenali (tamu, staf, pengantin)"],
  ota_listing: ["OTA listing text", "Teks listing OTA"],
  negative_review: ["Reply to a negative review or complaint", "Balasan review/keluhan negatif"],
  paid_ads: ["Paid ad or boosted post", "Iklan berbayar atau post di-boost"],
  influencer: ["Influencer, endorsement or barter stay", "Influencer, endorse, atau barter menginap"],
  religion_culture: ["Religion, custom, temple or ceremony", "Agama, adat, tempat suci, atau upacara"],
  crisis: ["Crisis, disaster, incident, legal/health/safety issue", "Krisis, bencana, insiden, isu hukum/kesehatan/keselamatan"],
};
export const FLAG_SOURCE_LABEL: Record<DraftFlag["source"], [string, string]> = {
  author: ["set by author", "dari pembuat"], server: ["automatic", "otomatis"], staff: ["added by staff", "ditambah staf"], qa: ["added in QA", "ditambah saat QA"],
};

/** Alasan level minimum dalam bahasa manusia (rule dari backend: intent:…, fact_claims, agent_draft, flag:…, source_draft:…). */
export function levelReason(rule: string, en: boolean): string {
  const [kind, value] = rule.split(":", 2);
  if (kind === "flag" && value in FLAG_LABEL) return FLAG_LABEL[value as ContentFlag][en ? 0 : 1];
  if (kind === "fact_claims") return en ? "Factual claims from the fact sheet" : "Ada klaim fakta dari fact sheet";
  if (kind === "agent_draft") return en ? "AI draft for a real client" : "Draft AI untuk klien nyata";
  if (kind === "source_draft") return en ? `Follows source draft #${value}` : `Mengikuti draft asal #${value}`;
  if (kind === "intent") return en ? `Minimum for ${value}` : `Minimum intent ${value}`;
  return rule;
}
export const EVIDENCE_LABELS = ["DATA FINAL", "ASSUMPTION", "CLIENT CONFIRMATION", "FIELD VERIFICATION", "RISK", "NEXT ACTION"] as const;
export const CLAIM_CATEGORIES = [
  "facility", "location", "price", "rating", "certification", "halal-dietary", "food-beverage",
  "treatment", "experience", "capacity", "safety", "license", "itinerary", "other",
] as const;
export const FACTUAL = CLAIM_CATEGORIES.filter((c) => c !== "experience" && c !== "other");
export const QA_GATES = ["claim-verification", "content-review", "privacy-rights-review", "visual-ai-review", "publication-checklist"] as const;
export const QA_RESULTS = ["Pass", "Conditional", "Fail", "N/A"] as const;
export const DECISIONS = ["Approved", "Revise", "Rejected"] as const;
export const VERTICALS = ["accommodation", "food-beverage", "spa-wellness", "experience", "wedding-event", "travel-tour"] as const;
export const FACT_KEY_RE = /^[a-z0-9]+([._-][a-z0-9]+)*$/;
// Referensi bukti/dokumen yang diterima backend (skema aman).
// Tanpa spasi, karakter kontrol, dan karakter tak terlihat (zero-width, bidi) yang memalsukan tampilan link.
export const REF_RE = /^(https:\/\/|mailto:|workspace:\/\/)[^\s\x00-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2060-\u2069\ufeff]+$/;

export const AGENCY_WRITERS = new Set(["owner", "content_lead", "content_staff"]);
export const SENIOR = new Set(["owner", "content_lead"]);

/** Peran & batas level untuk satu klien: membership agency diutamakan, lalu scope klien (sama dengan backend). */
export function memberFor(me: Me, client: string): Membership | undefined {
  return me.user.memberships.find((m) => m.scope === "agency") ?? me.user.memberships.find((m) => m.scope === client);
}

export function roleFor(me: Me, client: string): string {
  return memberFor(me, client)?.role ?? "";
}

/** Pemilik usaha langganan mandiri (kontrak 0.13.0): approver klien `self_serve` itu. Sama dengan backend. */
export function isSelfServeOwner(me: Me, client: Client | undefined): boolean {
  return !!client?.self_serve && roleFor(me, client.client_code) === "client_approver";
}

/** Daftar klien yang terlihat user (dimuat sekali setelah sesi siap). */
export function useClients(ready: boolean): Client[] {
  const [clients, setClients] = useState<Client[]>([]);
  useEffect(() => {
    if (!ready) return;
    api<{ items: Client[] }>("clients").then((r) => r.ok && setClients(r.data.items));
  }, [ready]);
  return clients;
}

/** Link hanya untuk https/mailto; workspace:// (arsip internal) ditampilkan sebagai teks. */
export function safeHref(ref: string | null | undefined): string | null {
  return ref && /^(https:\/\/|mailto:)/.test(ref) && REF_RE.test(ref) ? ref : null;
}

export function formatDate(iso: string | null, lang: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(lang === "id" ? "id-ID" : "en-GB", { dateStyle: "medium", timeStyle: iso.length > 10 ? "short" : undefined, timeZone: "Asia/Makassar" });
}

export type SessionState = "loading" | "ready" | "signed-out" | "unavailable" | "setup";

/** Sesi login: halaman workflow hanya untuk user yang sudah siap (password diganti, 2FA owner aktif). */
export function useSession(): { me: Me | null; state: SessionState } {
  const [me, setMe] = useState<Me | null>(null);
  const [state, setState] = useState<SessionState>("loading");
  useEffect(() => {
    api<Me>("auth/me").then((r) => {
      if (!r.ok) return setState(r.status === 401 ? "signed-out" : "unavailable");
      setMe(r.data);
      setState(r.data.next === "ready" ? "ready" : "setup");
    });
  }, []);
  return { me, state };
}

export const STATUS_TONE: Record<string, string> = {
  open: "neutral", in_progress: "info", approved: "success", rejected: "warning", closed: "neutral",
  pending: "neutral", ready: "info", confirmed: "success", corrected: "warning",
  Approved: "success", Revise: "warning", Rejected: "warning",
  Pass: "success", Conditional: "info", Fail: "warning", "N/A": "neutral",
};

export const STATUS_LABEL: Record<string, [string, string]> = {
  open: ["Open", "Baru"], in_progress: ["In progress", "Dikerjakan"], approved: ["Approved", "Disetujui"],
  rejected: ["Rejected", "Ditolak"], closed: ["Closed", "Ditutup"],
  pending: ["Waiting for client", "Menunggu klien"], ready: ["Ready to approve", "Siap disetujui"],
  confirmed: ["Confirmed", "Benar"], corrected: ["Corrected", "Dikoreksi"],
  Approved: ["Approved", "Disetujui"], Revise: ["Revise", "Revisi"], Rejected: ["Rejected", "Ditolak"],
};
