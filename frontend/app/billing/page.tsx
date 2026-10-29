"use client";

import { useCallback, useEffect, useState } from "react";
import { Card, Kpi, PageHeader } from "../../components/ui";
import { Field, Notice } from "../../components/WorkflowUi";
import { api, errorText, isOwner, type Me } from "../../lib/auth";
import { LOW_CREDITS, REASON, rupiah, type Catalog, type CreditEntry, type Payment, type Wallet } from "../../lib/billing";
import { L, useL, useLang } from "../../lib/i18n";
import { formatDate, type Client } from "../../lib/workflow";

type State = "loading" | "ready" | "signed-out" | "unavailable";

/** Kredit & langganan klien: saldo, paket, top up, riwayat (AI-CONSTITUTION v4.0.0 §4b). */
export default function BillingPage() {
  const tr = useL();
  const { lang } = useLang();
  const [state, setState] = useState<State>("loading");
  const [me, setMe] = useState<Me | null>(null);
  const [clients, setClients] = useState<Client[]>([]);
  const [code, setCode] = useState("");
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [wallet, setWallet] = useState<Wallet | null>(null);
  const [ledger, setLedger] = useState<CreditEntry[]>([]);
  const [payments, setPayments] = useState<Payment[]>([]);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  // Paket yang dipilih di situs publik (?paket=12 → /daftar → verifikasi → sini).
  const [suggested, setSuggested] = useState<number | null>(null);

  const load = useCallback(async (c: string) => {
    const [w, l, p] = await Promise.all([
      api<Wallet>(`billing/wallet?client_code=${c}`),
      api<{ items: CreditEntry[] }>(`billing/ledger?client_code=${c}&limit=30`),
      api<{ items: Payment[] }>(`billing/payments?client_code=${c}&limit=10`),
    ]);
    if (w.ok) setWallet(w.data);
    else setMsg({ ok: false, text: errorText(w, lang) });
    if (l.ok) setLedger(l.data.items);
    if (p.ok) setPayments(p.data.items);
  }, [lang]);

  useEffect(() => {
    document.title = `${tr("Credits & plan", "Kredit & paket")} · CLAU AI`;
    const pick = Number(new URLSearchParams(window.location.search).get("paket"));
    if ([1, 3, 6, 12].includes(pick)) setSuggested(pick);
    const pick = Number(new URLSearchParams(window.location.search).get("paket"));
    if ([1, 3, 6, 12].includes(pick)) setSuggested(pick);
    api<Catalog>("billing/catalog").then((r) => r.ok && setCatalog(r.data));
    api<Me>("auth/me").then(async (m) => {
      if (!m.ok) return setState(m.status === 401 ? "signed-out" : "unavailable");
      setMe(m.data);
      const c = await api<{ items: Client[] }>("clients");
      if (c.ok) {
        setClients(c.data.items);
        if (c.data.items[0]) setCode(c.data.items[0].client_code);
      }
      setState("ready");
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    if (state === "ready" && code) load(code);
  }, [state, code, load]);

  const canPay = !!me && (isOwner(me) || me.user.memberships.some((m) => m.scope === code && m.role === "client_approver"));

  async function pay(body: { kind: "subscription" | "topup"; plan_months?: number; topup_credits?: number }) {
    setMsg(null);
    const r = await api<Payment>("billing/checkout", { method: "POST", body: { client_code: code, ...body } });
    if (!r.ok) return setMsg({ ok: false, text: errorText(r, lang) });
    try {
      window.localStorage.removeItem("clau_plan");
    } catch {
      /* storage tidak tersedia */
    }
    if (r.data.payment_url) {
      window.location.assign(r.data.payment_url);
      return;
    }
    setMsg({ ok: true, text: tr(`Invoice ${r.data.order_id} created (test mode).`, `Tagihan ${r.data.order_id} dibuat (mode uji).`) });
    load(code);
  }

  async function simulate(id: number) {
    const r = await api<Payment>(`billing/payments/${id}/simulate-paid`, { method: "POST" });
    setMsg(r.ok ? { ok: true, text: tr("Marked as paid (test mode).", "Ditandai lunas (mode uji).") } : { ok: false, text: errorText(r, lang) });
    load(code);
  }

  const header = (
    <PageHeader
      title={<L en="Credits & plan" id="Kredit & paket" />}
      subtitle={<L en="Every AI job uses credits shown before it runs. Out of credits = agents pause; failed jobs give credits back." id="Setiap job AI memakai kredit yang tampil sebelum dijalankan. Kredit habis = agent berhenti; job gagal = kredit kembali." />}
    />
  );
  if (state !== "ready")
    return (
      <>
        {header}
        {state !== "loading" && (
          <Card>
            <p className="muted">
              {state === "signed-out" ? tr("Please sign in.", "Silakan masuk.") : tr("Sign-in is not active on this server yet.", "Login belum aktif di server ini.")}
            </p>
          </Card>
        )}
      </>
    );

  const low = wallet && !wallet.simulation && wallet.balance.total < LOW_CREDITS;
  return (
    <>
      {header}
      <div className="wf-row">
        <Field id="bill-client" label={tr("Client", "Klien")}>
          <select id="bill-client" value={code} onChange={(e) => setCode(e.target.value)}>
            {clients.map((c) => <option key={c.client_code} value={c.client_code}>{c.client_code}{c.simulation ? " · SIMULASI" : ""}</option>)}
          </select>
        </Field>
      </div>
      <Notice msg={msg} />
      {wallet && (
        <>
          {low && (
            <p className="auth-notice auth-notice--error" role="alert">
              {wallet.balance.total === 0
                ? tr("Out of credits: agents are paused. Top up below to continue.", "Kredit habis: agent berhenti. Top up di bawah untuk melanjutkan.")
                : tr(`Only ${wallet.balance.total} credits left. Top up so scheduled work doesn't stop.`, `Kredit tinggal ${wallet.balance.total}. Top up agar pekerjaan terjadwal tidak terhenti.`)}
            </p>
          )}
          {wallet.simulation && <p className="muted">{tr("SIMULATION client: AI jobs are free (test mode).", "Klien SIMULASI: job AI gratis (mode uji).")}</p>}
          <div className="kpis">
            <Kpi label={tr("Credits left", "Sisa kredit")} value={wallet.balance.total.toLocaleString("id-ID")}
              hint={tr(`monthly ${wallet.balance.monthly} · top up ${wallet.balance.topup}`, `bulanan ${wallet.balance.monthly} · top up ${wallet.balance.topup}`)} />
            <Kpi label={tr("Plan", "Paket")} value={wallet.subscription ? tr(`${wallet.subscription.plan_months} mo`, `${wallet.subscription.plan_months} bln`) : "—"}
              hint={wallet.subscription ? tr(`until ${formatDate(wallet.subscription.ends_at, lang)}`, `s.d. ${formatDate(wallet.subscription.ends_at, lang)}`) : tr("No active plan", "Belum ada paket aktif")} />
            <Kpi label={tr("Next reset", "Reset berikutnya")} value={wallet.subscription?.next_reset ? formatDate(wallet.subscription.next_reset, lang) : "—"} />
          </div>
        </>
      )}
      <div className="users-layout">
        <div className="stack">
          {catalog && (
            <Card title={<L en="Plans" id="Paket" />}>
              <p className="muted">{tr(`All agents, ${catalog.monthly_credits} credits every month. Not renewed automatically.`, `Semua agent, ${catalog.monthly_credits} kredit setiap bulan. Tidak diperpanjang otomatis.`)}</p>
              {suggested && !wallet?.subscription && (
                <p className="auth-notice">{tr(`You picked the ${suggested}-month plan. Pay below to activate your AI team.`, `Anda memilih paket ${suggested} bulan. Bayar di bawah untuk mengaktifkan tim AI.`)}</p>
              )}
              <div className="wf-row">
                {catalog.plans.map((p) => (
                  <button key={p.plan_months} type="button" className={p.plan_months === suggested && !wallet?.subscription ? "btn btn--primary" : "btn"} disabled={!canPay} onClick={() => pay({ kind: "subscription", plan_months: p.plan_months })}>
                    {tr(`${p.plan_months} mo`, `${p.plan_months} bln`)} · {rupiah(p.price_idr)}{p.save_pct ? ` (-${p.save_pct}%)` : ""}
                  </button>
                ))}
              </div>
              <h3 className="wf-subtitle">{tr("Top up", "Top up")}</h3>
              <div className="wf-row">
                {catalog.topups.map((t) => (
                  <button key={t.credits} type="button" className="btn btn--primary" disabled={!canPay} onClick={() => pay({ kind: "topup", topup_credits: t.credits })}>
                    {t.credits.toLocaleString("id-ID")} {tr("credits", "kredit")} · {rupiah(t.price_idr)}
                  </button>
                ))}
              </div>
              {!canPay && <p className="muted wf-hint">{tr("Only the owner or the client's approver can pay.", "Hanya owner atau approver klien yang bisa membayar.")}</p>}
            </Card>
          )}
          <Card title={<L en="Credit history" id="Riwayat kredit" />} flush>
            {ledger.length === 0 ? (
              <p className="muted wf-empty">{tr("No credit activity yet.", "Belum ada aktivitas kredit.")}</p>
            ) : (
              <div className="table-wrap">
                <table className="table">
                  <thead><tr><th>{tr("When", "Waktu")}</th><th>{tr("What", "Keterangan")}</th><th>{tr("Credits", "Kredit")}</th></tr></thead>
                  <tbody>
                    {ledger.map((e) => (
                      <tr key={e.id}>
                        <td className="muted">{formatDate(e.created_at, lang)}</td>
                        <td>{REASON[e.reason][lang === "id" ? 1 : 0]}{e.ai_job_id ? ` #${e.ai_job_id}` : ""}{e.note ? ` · ${e.note}` : ""}</td>
                        <td>{e.delta > 0 ? `+${e.delta}` : e.delta}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </div>
        <div className="stack">
          <Card title={<L en="Invoices" id="Tagihan" />} flush>
            {payments.length === 0 ? (
              <p className="muted wf-empty">{tr("No invoices yet.", "Belum ada tagihan.")}</p>
            ) : (
              <div className="table-wrap">
                <table className="table">
                  <thead><tr><th>{tr("Item", "Item")}</th><th>{tr("Amount", "Nominal")}</th><th>Status</th></tr></thead>
                  <tbody>
                    {payments.map((p) => (
                      <tr key={p.id}>
                        <td>{p.kind === "subscription" ? tr(`${p.plan_months}-month plan`, `Paket ${p.plan_months} bulan`) : tr(`${p.credits} credits`, `${p.credits} kredit`)}</td>
                        <td>{rupiah(p.amount_idr)}</td>
                        <td>
                          {p.status}
                          {p.status === "pending" && p.provider === "fake" && me && isOwner(me) && (
                            <button type="button" className="btn btn--sm" onClick={() => simulate(p.id)}>{tr("Mark paid (test)", "Tandai lunas (uji)")}</button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
          {catalog && (
            <Card title={<L en="Credits per job" id="Kredit per pekerjaan" />} flush>
              <div className="table-wrap">
                <table className="table">
                  <thead><tr><th>{tr("Job", "Pekerjaan")}</th><th>Agent</th><th>{tr("Credits", "Kredit")}</th></tr></thead>
                  <tbody>
                    {catalog.credit_costs.map((c) => (
                      <tr key={c.intent}><td>{c.intent}</td><td>{c.agent ?? "—"}{c.status !== "active" ? ` · ${tr("soon", "segera")}` : ""}</td><td>{c.credits}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}
