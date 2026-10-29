"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type Me } from "../lib/auth";
import type { Wallet } from "../lib/billing";
import { useL } from "../lib/i18n";
import { isSelfServeOwner, type Client, type FactSheet, type Page, type WfRequest } from "../lib/workflow";

type Step = { done: boolean; en: string; id: string; href: string; cta: [string, string] };

/**
 * Langkah awal pemilik usaha langganan mandiri (TASK-007): bayar paket → isi Brain bisnis → minta konten pertama →
 * setujui. Hanya tampil untuk approver klien `self_serve`; hilang sendiri setelah semua langkah selesai.
 */
export default function Onboarding() {
  const tr = useL();
  const [steps, setSteps] = useState<Step[] | null>(null);

  useEffect(() => {
    let live = true;
    (async () => {
      const m = await api<Me>("auth/me");
      if (!m.ok || m.data.next !== "ready") return;
      const c = await api<{ items: Client[] }>("clients");
      const client = c.ok ? c.data.items.find((x) => isSelfServeOwner(m.data, x)) : undefined;
      if (!client) return;
      const code = encodeURIComponent(client.client_code);
      const [w, s, r] = await Promise.all([
        api<Wallet>(`billing/wallet?client_code=${code}`),
        api<Page<FactSheet>>(`fact-sheets?client_code=${code}&approved=true&limit=1`),
        api<Page<WfRequest>>(`requests?client_code=${code}&limit=50`),
      ]);
      if (!live) return;
      const requests = r.ok ? r.data.items : [];
      setSteps([
        { done: w.ok && !!w.data.subscription?.active, en: "Activate a plan", id: "Aktifkan paket", href: "/billing", cta: ["Choose a plan", "Pilih paket"] },
        { done: s.ok && s.data.total > 0, en: "Fill in your business Brain", id: "Isi Brain bisnis", href: "/fact-sheets", cta: ["Add facts", "Isi fakta"] },
        { done: requests.length > 0, en: "Ask an agent for your first content", id: "Minta konten pertama ke agen", href: "/requests", cta: ["New request", "Permintaan baru"] },
        { done: requests.some((x) => x.status === "approved"), en: "Review and approve it", id: "Periksa dan setujui", href: "/requests", cta: ["Open requests", "Buka permintaan"] },
      ]);
    })();
    return () => {
      live = false;
    };
  }, []);

  if (!steps || steps.every((s) => s.done)) return null;
  const next = steps.findIndex((s) => !s.done);
  return (
    <section className="panel onboarding" aria-labelledby="onboarding-title">
      <h2 id="onboarding-title">{tr("Get your AI team working", "Mulai pakai tim AI kamu")}</h2>
      <p className="muted">
        {tr("Four steps, no staff needed. Nothing is posted until you approve it.", "Empat langkah, tanpa perlu staf. Tidak ada yang tayang sebelum kamu setujui.")}
      </p>
      <ol className="onboarding__steps">
        {steps.map((s, i) => (
          <li key={s.en} className={s.done ? "is-done" : i === next ? "is-next" : undefined}>
            <span className="onboarding__dot" aria-hidden="true">{s.done ? "✓" : i + 1}</span>
            <span className="onboarding__label">
              {tr(s.en, s.id)}
              <span className="sr-only">{s.done ? tr(" (done)", " (selesai)") : ""}</span>
            </span>
            {i === next && <Link className="btn btn--primary btn--sm" href={s.href}>{tr(...s.cta)}</Link>}
          </li>
        ))}
      </ol>
    </section>
  );
}
