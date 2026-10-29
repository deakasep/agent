"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { Card, PageHeader } from "../../components/ui";
import { api, errorText, type Me } from "../../lib/auth";
import { L, useL, useLang } from "../../lib/i18n";

/** Buka tautan dari email (?token=…) → akun aktif + langsung masuk, lalu ke pilih paket. Tanpa token: minta tautan baru. */
export default function VerifyEmailPage() {
  const tr = useL();
  const { lang } = useLang();
  const [state, setState] = useState<"checking" | "ask" | "sent" | "error">("checking");
  const [error, setError] = useState("");
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const started = useRef(false);

  useEffect(() => {
    document.title = `${tr("Verify email", "Verifikasi email")} · CLAU AI`;
    if (started.current) return;
    started.current = true;
    const token = new URLSearchParams(window.location.search).get("token");
    if (!token) return setState("ask");
    // Token dihapus dari address bar (tidak tersimpan di riwayat / terbawa saat link dibagikan).
    window.history.replaceState(null, "", "/verifikasi-email");
    api<Me>("auth/verify-email", { method: "POST", body: { token } }).then((r) => {
      if (r.ok) {
        let plan = "";
        try {
          plan = window.localStorage.getItem("clau_plan") ?? "";
        } catch {
          /* storage tidak tersedia */
        }
        window.location.assign(plan ? `/billing?paket=${encodeURIComponent(plan)}` : "/billing");
        return;
      }
      setError(errorText(r, lang));
      setState("error");
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function resend(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    const r = await api<{ ok: true }>("auth/verification-email", { method: "POST", body: { email } });
    setBusy(false);
    if (r.ok) setState("sent");
    else {
      setError(errorText(r, lang));
      setState("error");
    }
  }

  return (
    <>
      <PageHeader title={<L en="Verify your email" id="Verifikasi email" />} />
      <div className="auth-narrow">
        <Card>
          {state === "checking" && <p className="muted">{tr("Checking your link…", "Memeriksa tautan…")}</p>}
          {state === "sent" && (
            <p role="status">{tr("If that email is waiting for verification, a new link is on its way.", "Bila email itu menunggu verifikasi, tautan baru sedang dikirim.")}</p>
          )}
          {(state === "ask" || state === "error") && (
            <form onSubmit={resend} className="auth-form" noValidate>
              {state === "error" && (
                <p className="auth-error" role="alert">
                  {error}
                </p>
              )}
              <p className="muted">{tr("Enter your email and we'll send a new verification link.", "Masukkan email Anda, kami kirim tautan verifikasi baru.")}</p>
              <div className="field">
                <label htmlFor="email">Email</label>
                <input id="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
              </div>
              <button type="submit" className="btn btn--primary" disabled={busy || !/.+@.+\..+/.test(email)}>
                {busy ? tr("Sending…", "Mengirim…") : tr("Send new link", "Kirim tautan baru")}
              </button>
              <p className="muted">
                <a href="/login">{tr("Back to sign in", "Kembali ke halaman masuk")}</a>
              </p>
            </form>
          )}
        </Card>
      </div>
    </>
  );
}
