"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type Me } from "../lib/auth";
import { LOW_CREDITS, type Wallet } from "../lib/billing";
import { useL } from "../lib/i18n";

/**
 * Pemberitahuan kredit di semua halaman dashboard (AI-CONSTITUTION v4.0.0 §4b).
 * Klien tidak mengurus API key atau akun AI: sistem memakai kredit otomatis, klien hanya diberi tahu saat kredit
 * menipis atau habis, lalu top up di /billing. Hanya untuk akun klien (scope client_code) dan klien NYATA.
 */
export default function CreditAlert() {
  const tr = useL();
  const [wallet, setWallet] = useState<Wallet | null>(null);

  useEffect(() => {
    let live = true;
    api<Me>("auth/me").then(async (m) => {
      if (!m.ok || m.data.next !== "ready") return;
      const client = m.data.user.memberships.find((x) => x.scope !== "agency");
      if (!client) return;
      const w = await api<Wallet>(`billing/wallet?client_code=${encodeURIComponent(client.scope)}`);
      if (live && w.ok) setWallet(w.data);
    });
    return () => {
      live = false;
    };
  }, []);

  if (!wallet || wallet.simulation || wallet.balance.total >= LOW_CREDITS) return null;
  const empty = wallet.balance.total <= 0;
  return (
    <p className={`auth-notice${empty ? " auth-notice--error" : ""}`} role="alert">
      {empty
        ? tr("Out of credits: your agents are paused. Drafts already made are kept.", "Kredit habis: agent berhenti bekerja. Draft yang sudah jadi tetap tersimpan.")
        : tr(`Credits running low: ${wallet.balance.total} left.`, `Kredit menipis: tinggal ${wallet.balance.total}.`)}{" "}
      <Link href="/billing">{tr("Top up now", "Top up sekarang")}</Link>
    </p>
  );
}
