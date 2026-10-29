"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import CreditAlert from "./CreditAlert";
import Icon, { type IconName } from "./Icon";
import UserMenu from "./UserMenu";
import Logo from "./Logo";
import { L, useL, useLang } from "../lib/i18n";
import { useTheme } from "../lib/theme";
import { useDialog } from "../lib/useDialog";

type Item = { href: string; en: string; id: string; icon: IconName; count?: number };
type Group = { en: string; id: string; items: Item[] };

export default function AppShell({ children, activeAgents }: { children: ReactNode; activeAgents: number }) {
  const NAV: Group[] = [
    { en: "Home", id: "Beranda", items: [{ href: "/", en: "Dashboard", id: "Dashboard", icon: "dashboard" }] },
    {
      en: "AI Workforce",
      id: "Tim AI",
      items: [
        { href: "/team", en: "My AI Team", id: "Tim AI Saya", icon: "team", count: activeAgents },
        { href: "/agents", en: "Agents", id: "Agent", icon: "bot" },
        { href: "/workflows", en: "Workflows", id: "Alur kerja", icon: "workflow" },
      ],
    },
    {
      en: "Workspace",
      id: "Workspace",
      items: [
        { href: "/requests", en: "Requests", id: "Permintaan", icon: "inbox" },
        { href: "/fact-sheets", en: "Fact sheets", id: "Fact sheet", icon: "shield" },
        { href: "/clients", en: "Clients", id: "Klien", icon: "users" },
        { href: "/projects", en: "Projects", id: "Proyek", icon: "folder" },
        { href: "/content", en: "Content", id: "Konten", icon: "content" },
        { href: "/calendar", en: "Calendar", id: "Kalender", icon: "calendar" },
      ],
    },
    { en: "Insights", id: "Insight", items: [{ href: "/reports", en: "Reports", id: "Laporan", icon: "reports" }] },
    {
      en: "System",
      id: "Sistem",
      items: [
        { href: "/settings", en: "Settings", id: "Pengaturan", icon: "settings" },
        { href: "/account", en: "Account", id: "Akun", icon: "user" },
        { href: "/users", en: "Users", id: "Pengguna", icon: "users" },
        { href: "/ai-usage", en: "AI usage", id: "Pemakaian AI", icon: "sparkles" },
        { href: "/billing", en: "Credits & plan", id: "Kredit & paket", icon: "reports" },
      ],
    },
  ];

  const path = usePathname() ?? "/";
  const [open, setOpen] = useState(false);
  const { lang, setLang } = useLang();
  const { resolved, setPref } = useTheme();
  const tr = useL();
  useEffect(() => setOpen(false), [path]);
  // Menu HP: fokus masuk ke menu, Esc menutup, halaman di belakang tidak ikut tergulir.
  const sidebar = useDialog<HTMLElement>(open, () => setOpen(false));

  const isActive = (href: string) => (href === "/" ? path === "/" : path === href || path.startsWith(`${href}/`));
  const current = NAV.flatMap((g) => g.items).filter((i) => isActive(i.href)).pop();
  const dark = resolved === "dark";

  return (
    <div className="shell">
      <aside ref={sidebar} tabIndex={-1} className={`sidebar${open ? " sidebar--open" : ""}`} aria-label={tr("Main navigation", "Navigasi utama")}>
        <div className="sidebar__brand">
          <Link href="/" aria-label="Dashboard">
            <Logo />
          </Link>
          <button type="button" className="icon-btn icon-btn--ghost sidebar__close" onClick={() => setOpen(false)} aria-label={tr("Close menu", "Tutup menu")}>
            <Icon name="x" />
          </button>
        </div>
        <nav>
          {NAV.map((g) => (
            <div key={g.en} className="nav-group">
              <span className="nav-group__label">{lang === "id" ? g.id : g.en}</span>
              {g.items.map((i) => (
                <Link
                  key={i.href}
                  href={i.href}
                  className={`nav-item${isActive(i.href) ? " nav-item--active" : ""}`}
                  aria-current={isActive(i.href) ? "page" : undefined}
                  title={lang === "id" ? i.id : i.en}
                >
                  <Icon name={i.icon} size={18} />
                  {lang === "id" ? i.id : i.en}
                  {i.count !== undefined && <span className="nav-item__count">{i.count}</span>}
                </Link>
              ))}
            </div>
          ))}
        </nav>
        <div className="sidebar__foot">
          <b>
            <Icon name="shield" size={14} />
            <L en="Humans stay in control" id="Manusia tetap memegang kendali" />
          </b>
          <L en="Agents prepare drafts. Your team approves and publishes." id="Agent menyiapkan draft. Tim kamu yang menyetujui dan mempublish." />
        </div>
      </aside>
      {open && <button type="button" className="scrim" aria-label={tr("Close menu", "Tutup menu")} onClick={() => setOpen(false)} />}

      <div className="main">
        <header className="topbar">
          <button type="button" className="icon-btn icon-btn--ghost topbar__menu" onClick={() => setOpen(true)} aria-label={tr("Open menu", "Buka menu")} aria-expanded={open}>
            <Icon name="menu" />
          </button>
          <span className="topbar__title">{current ? (lang === "id" ? current.id : current.en) : "CLAU"}</span>
          <div className="topbar__search" title={tr("Search will be available once the backend is connected", "Pencarian tersedia setelah backend tersambung")}>
            <Icon name="search" size={16} />
            <input type="search" placeholder={tr("Search…", "Cari…")} aria-label={tr("Search", "Cari")} disabled />
          </div>
          <span className="pill" title={tr("Preview with sample data", "Pratinjau dengan data contoh")}>
            <span className="pill__dot" />
            <L en="Simulation mode" id="Mode simulasi" />
          </span>
          <div className="seg" role="group" aria-label={tr("Language", "Bahasa")}>
            <button type="button" aria-pressed={lang === "en"} onClick={() => setLang("en")} title="English">
              EN
            </button>
            <button type="button" aria-pressed={lang === "id"} onClick={() => setLang("id")} title="Bahasa Indonesia">
              ID
            </button>
          </div>
          <button
            type="button"
            className="icon-btn icon-btn--ghost"
            onClick={() => setPref(dark ? "light" : "dark")}
            aria-label={dark ? tr("Switch to light mode", "Ganti ke mode terang") : tr("Switch to dark mode", "Ganti ke mode gelap")}
            title={dark ? tr("Light mode", "Mode terang") : tr("Dark mode", "Mode gelap")}
          >
            <Icon name={dark ? "sun" : "moon"} size={18} />
          </button>
          <button type="button" className="icon-btn icon-btn--ghost topbar__notify" aria-label={tr("Notifications (not available yet)", "Notifikasi (belum tersedia)")} disabled>
            <Icon name="bell" size={18} />
          </button>
          <UserMenu />
        </header>
        <main className="content">
          <CreditAlert />
          {children}
        </main>
      </div>
    </div>
  );
}
