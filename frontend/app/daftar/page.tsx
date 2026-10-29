"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Card, PageHeader } from "../../components/ui";
import { api, errorText } from "../../lib/auth";
import { L, useL, useLang } from "../../lib/i18n";

// Nilai sama dengan backend VERTICALS (app/db/models.py, migrasi 0009).
const VERTICALS: { id: string; en: string; idn: string }[] = [
  { id: "retail", en: "Shop / online store", idn: "Toko / online shop" },
  { id: "food-beverage", en: "Restaurant, café, food", idn: "Restoran, kafe, kuliner" },
  { id: "services", en: "Services (salon, repair, studio…)", idn: "Jasa (salon, bengkel, studio…)" },
  { id: "accommodation", en: "Villa, hotel, homestay", idn: "Villa, hotel, homestay" },
  { id: "wedding-event", en: "Wedding & events", idn: "Wedding & event" },
  { id: "travel-tour", en: "Travel & tours", idn: "Travel & tur" },
  { id: "spa-wellness", en: "Spa & wellness", idn: "Spa & wellness" },
  { id: "experience", en: "Tourism experience", idn: "Wisata & aktivitas" },
  { id: "other", en: "Other", idn: "Lainnya" },
];
const TIMEZONES = [
  { id: "Asia/Jakarta", label: "WIB" },
  { id: "Asia/Makassar", label: "WITA" },
  { id: "Asia/Jayapura", label: "WIT" },
];

/** Daftar mandiri (TASK-003): klien baru + akun pemilik. Email wajib diverifikasi sebelum bisa masuk. */
export default function SignupPage() {
  const tr = useL();
  const { lang } = useLang();
  const [f, setF] = useState({ business_name: "", display_name: "", email: "", password: "", vertical: "retail", business_type: "", location_area: "", timezone: "Asia/Makassar" });
  const [terms, setTerms] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  const [plan, setPlan] = useState<string | null>(null);
  const [site, setSite] = useState("");

  useEffect(() => {
    document.title = `${tr("Sign up", "Daftar")} · CLAU AI`;
    setSite(siteUrl());
    const p = new URLSearchParams(window.location.search).get("paket");
    if (p && /^(1|3|6|12)$/.test(p)) {
      setPlan(p);
      try {
        window.localStorage.setItem("clau_plan", p);
      } catch {
        /* storage tidak tersedia */
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const body = { ...f, location_area: f.location_area || undefined, accept_terms: terms };
    const r = await api<{ ok: true }>("auth/signup", { method: "POST", body });
    setBusy(false);
    if (r.ok) setDone(true);
    else setError(r.code === "validation_error" ? tr("Please check every field.", "Periksa lagi semua kolom.") : errorText(r, lang));
  }

  const valid = f.business_name.trim().length >= 2 && f.display_name.trim() && /.+@.+\..+/.test(f.email) && f.password.length >= 12 && f.business_type.trim() && terms;

  return (
    <>
      <PageHeader
        title={<L en="Create your account" id="Buat akun" />}
        subtitle={
          plan ? (
            <L en={`Then choose the ${plan}-month plan and pay to activate your AI team.`} id={`Setelah itu pilih paket ${plan} bulan dan bayar untuk mengaktifkan tim AI Anda.`} />
          ) : (
            <L en="One account for your business. Your AI team is active once you pick a plan." id="Satu akun untuk usaha Anda. Tim AI aktif setelah Anda memilih paket." />
          )
        }
      />
      <div className="auth-narrow">
        <Card>
          {done ? (
            <div className="auth-form" role="status">
              <p>
                <strong>{tr("Check your inbox", "Cek email Anda")}</strong>
              </p>
              <p className="muted">
                {tr(
                  `If ${f.email} can be used, we've sent a verification link. Open it within 48 hours to activate your account.`,
                  `Bila ${f.email} bisa dipakai, kami sudah mengirim tautan verifikasi. Buka dalam 48 jam untuk mengaktifkan akun.`,
                )}
              </p>
              <a className="btn" href="/verifikasi-email">
                {tr("Didn't get the email?", "Belum menerima email?")}
              </a>
            </div>
          ) : (
            <form onSubmit={submit} className="auth-form" noValidate>
              <div className="field">
                <label htmlFor="business_name">{tr("Business name", "Nama usaha")}</label>
                <input id="business_name" autoComplete="organization" required maxLength={80} value={f.business_name} onChange={set("business_name")} />
              </div>
              <div className="field">
                <label htmlFor="vertical">{tr("Business category", "Kategori usaha")}</label>
                <select id="vertical" value={f.vertical} onChange={set("vertical")}>
                  {VERTICALS.map((v) => (
                    <option key={v.id} value={v.id}>{lang === "id" ? v.idn : v.en}</option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor="business_type">{tr("What do you sell? (e.g. coffee shop, batik store)", "Usaha Anda apa? (mis. kedai kopi, toko batik)")}</label>
                <input id="business_type" required maxLength={60} value={f.business_type} onChange={set("business_type")} />
              </div>
              <div className="wf-row">
                <div className="field">
                  <label htmlFor="location_area">{tr("City (optional)", "Kota (opsional)")}</label>
                  <input id="location_area" autoComplete="address-level2" maxLength={120} value={f.location_area} onChange={set("location_area")} />
                </div>
                <div className="field">
                  <label htmlFor="timezone">{tr("Time zone", "Zona waktu")}</label>
                  <select id="timezone" value={f.timezone} onChange={set("timezone")}>
                    {TIMEZONES.map((t) => (
                      <option key={t.id} value={t.id}>{t.label}</option>
                    ))}
                  </select>
                </div>
              </div>
              <div className="field">
                <label htmlFor="display_name">{tr("Your name", "Nama Anda")}</label>
                <input id="display_name" autoComplete="name" required maxLength={120} value={f.display_name} onChange={set("display_name")} />
              </div>
              <div className="field">
                <label htmlFor="email">Email</label>
                <input id="email" type="email" autoComplete="email" required value={f.email} onChange={set("email")} />
              </div>
              <div className="field">
                <label htmlFor="password">{tr("Password (at least 12 characters)", "Password (minimal 12 karakter)")}</label>
                <input id="password" type="password" autoComplete="new-password" required minLength={12} value={f.password} onChange={set("password")} />
                <span className="muted">{tr("Tip: a few unrelated words, e.g. kopi-sawah-pagi-2026", "Tips: gabungan beberapa kata, mis. kopi-sawah-pagi-2026")}</span>
              </div>
              <label className="check">
                <input type="checkbox" checked={terms} onChange={(e) => setTerms(e.target.checked)} />
                <span>
                  {tr("I agree to the ", "Saya menyetujui ")}
                  <a href={`${site}/syarat-layanan`} target="_blank" rel="noreferrer">{tr("Terms of Service", "Syarat Layanan")}</a>
                  {tr(" and ", " dan ")}
                  <a href={`${site}/kebijakan-privasi`} target="_blank" rel="noreferrer">{tr("Privacy Policy", "Kebijakan Privasi")}</a>.
                </span>
              </label>
              {error && (
                <p className="auth-error" role="alert">
                  {error}
                </p>
              )}
              <button type="submit" className="btn btn--primary" disabled={busy || !valid}>
                {busy ? tr("Creating…", "Membuat akun…") : tr("Create account", "Buat akun")}
              </button>
              <p className="muted">
                {tr("Already have an account? ", "Sudah punya akun? ")}
                <a href="/login">{tr("Sign in", "Masuk")}</a>
              </p>
            </form>
          )}
        </Card>
      </div>
    </>
  );
}

// Situs publik (repo web) ada di domain utama: app.domain-anda.com → domain-anda.com (/syarat-layanan, /kebijakan-privasi).
function siteUrl() {
  if (typeof window === "undefined") return "";
  const { protocol, host } = window.location;
  return host.startsWith("app.") ? `${protocol}//${host.slice(4)}` : "";
}
