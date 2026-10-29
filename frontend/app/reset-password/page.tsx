"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Card, PageHeader } from "../../components/ui";
import { api, errorText } from "../../lib/auth";
import { L, useL, useLang } from "../../lib/i18n";

export default function ResetPasswordPage() {
  const tr = useL();
  const { lang } = useLang();
  const [token, setToken] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    document.title = `${tr("New password", "Password baru")} · CLAU AI`;
    const t = new URLSearchParams(window.location.search).get("token") ?? "";
    setToken(t);
    if (t) window.history.replaceState(null, "", "/reset-password");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const r = await api<{ ok: true }>("auth/password-reset/confirm", { method: "POST", body: { token, new_password: password } });
    setBusy(false);
    if (r.ok) setDone(true);
    else setError(errorText(r, lang));
  }

  return (
    <>
      <PageHeader title={<L en="Set a new password" id="Buat password baru" />} />
      <div className="auth-narrow">
        <Card>
          {done ? (
            <div className="auth-form" role="status">
              <p>{tr("Password changed. All devices were signed out.", "Password sudah diganti. Semua perangkat sudah dikeluarkan.")}</p>
              <a className="btn btn--primary" href="/login">{tr("Sign in", "Masuk")}</a>
            </div>
          ) : !token ? (
            <p className="muted">
              {tr("This page needs the link from your email. ", "Halaman ini butuh tautan dari email Anda. ")}
              <a href="/lupa-password">{tr("Request a new link", "Minta tautan baru")}</a>
            </p>
          ) : (
            <form onSubmit={submit} className="auth-form" noValidate>
              <div className="field">
                <label htmlFor="password">{tr("New password (at least 12 characters)", "Password baru (minimal 12 karakter)")}</label>
                <input id="password" type="password" autoComplete="new-password" required minLength={12} value={password} onChange={(e) => setPassword(e.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="confirm">{tr("Repeat new password", "Ulangi password baru")}</label>
                <input id="confirm" type="password" autoComplete="new-password" required value={confirm} onChange={(e) => setConfirm(e.target.value)} />
              </div>
              {confirm && confirm !== password && <p className="auth-error">{tr("Passwords don't match.", "Password tidak sama.")}</p>}
              {error && (
                <p className="auth-error" role="alert">
                  {error}
                </p>
              )}
              <button type="submit" className="btn btn--primary" disabled={busy || password.length < 12 || password !== confirm}>
                {busy ? tr("Saving…", "Menyimpan…") : tr("Save new password", "Simpan password baru")}
              </button>
            </form>
          )}
        </Card>
      </div>
    </>
  );
}
