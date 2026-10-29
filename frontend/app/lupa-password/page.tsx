"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Card, PageHeader } from "../../components/ui";
import { api, errorText } from "../../lib/auth";
import { L, useL, useLang } from "../../lib/i18n";

export default function ForgotPasswordPage() {
  const tr = useL();
  const { lang } = useLang();
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    document.title = `${tr("Forgot password", "Lupa password")} · CLAU AI`;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const r = await api<{ ok: true }>("auth/password-reset", { method: "POST", body: { email } });
    setBusy(false);
    if (r.ok) setSent(true);
    else setError(errorText(r, lang));
  }

  return (
    <>
      <PageHeader title={<L en="Forgot password" id="Lupa password" />} subtitle={<L en="We'll email you a link to set a new password." id="Kami kirim tautan ke email Anda untuk membuat password baru." />} />
      <div className="auth-narrow">
        <Card>
          {sent ? (
            <p role="status">
              {tr(
                "If an account uses that email, a reset link is on its way. It's valid for 60 minutes.",
                "Bila ada akun dengan email itu, tautan reset sedang dikirim. Tautan berlaku 60 menit.",
              )}
            </p>
          ) : (
            <form onSubmit={submit} className="auth-form" noValidate>
              <div className="field">
                <label htmlFor="email">Email</label>
                <input id="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
              </div>
              {error && (
                <p className="auth-error" role="alert">
                  {error}
                </p>
              )}
              <button type="submit" className="btn btn--primary" disabled={busy || !/.+@.+\..+/.test(email)}>
                {busy ? tr("Sending…", "Mengirim…") : tr("Send reset link", "Kirim tautan reset")}
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
