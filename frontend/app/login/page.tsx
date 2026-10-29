"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Card, PageHeader } from "../../components/ui";
import { api, errorText, safeNext, type Me } from "../../lib/auth";
import { L, useL, useLang } from "../../lib/i18n";

export default function LoginPage() {
  const tr = useL();
  const { lang } = useLang();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [step, setStep] = useState<"password" | "totp" | "recovery">("password");
  const [error, setError] = useState("");
  const [notVerified, setNotVerified] = useState(false);
  const [busy, setBusy] = useState(false);
  const [next, setNext] = useState("/");
  // VPS 1 (pratinjau tanpa backend): form tidak ditampilkan, karena login memang belum aktif di sana.
  const [preview, setPreview] = useState(false);

  useEffect(() => {
    document.title = `${tr("Sign in", "Masuk")} · CLAU AI`;
    setNext(safeNext(new URLSearchParams(window.location.search).get("next")));
    api<Me>("auth/me").then((r) => {
      if (!r.ok && r.code === "backend_unavailable") setPreview(true);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const extra = step === "totp" ? { totp_code: code } : step === "recovery" ? { recovery_code: code } : {};
    const r = await api<Me>("auth/login", { method: "POST", body: { email, password, ...extra } });
    setBusy(false);
    if (r.ok) {
      window.location.assign(r.data.next === "ready" ? next : "/account");
      return;
    }
    if (r.code === "mfa_required") {
      setStep("totp");
      return;
    }
    setNotVerified(r.code === "email_not_verified");
    setError(errorText(r, lang));
  }

  function useRecovery() {
    setStep(step === "recovery" ? "totp" : "recovery");
    setCode("");
    setError("");
  }

  const codeValid = step === "totp" ? code.length === 6 : step === "recovery" ? code.replace(/[\s-]/g, "").length === 10 : true;

  return (
    <>
      <PageHeader title={<L en="Sign in" id="Masuk" />} subtitle={<L en="Business owners, approvers, and CLAU staff." id="Pemilik usaha, approver, dan staf CLAU." />} />
      <div className="auth-narrow">
        <Card>
          {preview ? (
            <p className="muted">
              <L en="Sign-in is not active on this server yet (preview with sample data)." id="Login belum aktif di server ini (pratinjau dengan data contoh)." />
            </p>
          ) : (
            <form onSubmit={submit} className="auth-form" noValidate>
              <div className="field">
                <label htmlFor="email">Email</label>
                <input id="email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} disabled={step !== "password"} />
              </div>
              <div className="field">
                <label htmlFor="password">
                  <L en="Password" id="Password" />
                </label>
                <input id="password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} disabled={step !== "password"} />
              </div>
              {step === "totp" && (
                <div className="field">
                  <label htmlFor="code">{tr("6-digit code from your authenticator app", "Kode 6 digit dari aplikasi authenticator")}</label>
                  <input id="code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} required autoFocus value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} />
                </div>
              )}
              {step === "recovery" && (
                <div className="field">
                  <label htmlFor="recovery">{tr("Backup code (e.g. abcde-fghij)", "Kode cadangan (mis. abcde-fghij)")}</label>
                  <input id="recovery" autoComplete="off" autoCapitalize="none" spellCheck={false} maxLength={20} required autoFocus value={code} onChange={(e) => setCode(e.target.value)} />
                </div>
              )}
              {error && (
                <p className="auth-error" role="alert">
                  {error}
                </p>
              )}
              <button type="submit" className="btn btn--primary" disabled={busy || !email || !password || !codeValid}>
                {busy ? tr("Checking…", "Memeriksa…") : step === "password" ? tr("Sign in", "Masuk") : tr("Verify", "Verifikasi")}
              </button>
              {step === "password" && (
                <p className="muted">
                  <a href="/lupa-password">{tr("Forgot password?", "Lupa password?")}</a>
                  {" · "}
                  {tr("New here? ", "Belum punya akun? ")}
                  <a href="/daftar">{tr("Create an account", "Daftar")}</a>
                </p>
              )}
              {error && notVerified && (
                <p className="muted">
                  <a href="/verifikasi-email">{tr("Send a new verification link", "Kirim ulang tautan verifikasi")}</a>
                </p>
              )}
              {step !== "password" && (
                <button type="button" className="link-btn" onClick={useRecovery}>
                  {step === "totp" ? tr("Lost your phone? Use a backup code", "HP hilang? Pakai kode cadangan") : tr("Use the authenticator app instead", "Pakai aplikasi authenticator saja")}
                </button>
              )}
            </form>
          )}
        </Card>
      </div>
    </>
  );
}
