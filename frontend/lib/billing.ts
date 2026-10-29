// Tipe & format langganan & kredit (kontrak core api-contracts 0.11.0 § Langganan & Kredit).

export type Catalog = {
  currency: "IDR";
  monthly_credits: number;
  plans: { plan_months: number; price_idr: number; save_pct: number }[];
  topups: { credits: number; price_idr: number }[];
  credit_costs: { intent: string; agent: string | null; credits: number; status: string }[];
};

export type Wallet = {
  client_code: string;
  balance: { monthly: number; topup: number; total: number };
  subscription: { plan_months: number; starts_at: string; ends_at: string; active: boolean; period_start: string; next_reset: string | null } | null;
  simulation: boolean;
};

export type CreditEntry = {
  id: number;
  client_code: string;
  delta: number;
  bucket: "monthly" | "topup";
  reason: "monthly_grant" | "monthly_expire" | "topup" | "usage" | "refund" | "adjustment";
  ai_job_id: number | null;
  payment_id: number | null;
  note: string | null;
  created_at: string;
};

export type Payment = {
  id: number;
  client_code: string;
  kind: "subscription" | "topup";
  plan_months: number | null;
  credits: number | null;
  amount_idr: number;
  provider: "fake" | "midtrans";
  order_id: string;
  status: "pending" | "paid" | "expired" | "failed";
  created_at: string;
  paid_at: string | null;
  payment_url?: string | null;
};

/** Batas pemberitahuan "kredit menipis" (≈ 10% dari 500 kredit bulanan). */
export const LOW_CREDITS = 50;

export const rupiah = (n: number) => "Rp" + n.toLocaleString("id-ID");

export const REASON: Record<CreditEntry["reason"], [string, string]> = {
  monthly_grant: ["Monthly credits", "Kredit bulanan"],
  monthly_expire: ["Unused monthly credits expired", "Sisa kredit bulanan hangus"],
  topup: ["Top up", "Top up"],
  usage: ["AI job", "Job AI"],
  refund: ["Refund (job failed or cancelled)", "Kredit kembali (job gagal/dibatalkan)"],
  adjustment: ["Adjustment by owner", "Penyesuaian owner"],
};
