import Link from "next/link";
import Avatar from "../components/Avatar";
import GenerateRun from "../components/GenerateRun";
import Icon from "../components/Icon";
import MemberCard from "../components/MemberCard";
import Onboarding from "../components/Onboarding";
import { Card, Kpi, Level, Progress, SimNotice, StatusBadge } from "../components/ui";
import { ACTIVITY, CLIENTS, CONTENT, PROJECTS, SIM_DATE, clientName } from "../lib/demo";
import { D, Greeting, L } from "../lib/i18n";
import { monthlyRun } from "../lib/run";
import { getMember, getTeam } from "../lib/team";

export default function Dashboard() {
  const team = getTeam();
  const active = team.filter((m) => m.status === "active");
  const pending = CONTENT.filter((c) => c.status === "ai_review" || c.status === "human_review");
  const published = CONTENT.filter((c) => c.status === "published");
  const upcoming = CONTENT.filter((c) => (c.status === "scheduled" || c.status === "approved") && c.date >= SIM_DATE)
    .sort((a, b) => a.date.localeCompare(b.date))
    .slice(0, 5);
  const featured = ["caption-writer", "reel-scripter", "story-writer", "listing-writer"].map((id) => getMember(id)!);

  return (
    <>
      <section className="hello">
        <div style={{ position: "relative", zIndex: 1 }}>
          <span className="online">
            <span className="pulse" />
            <L en={`${active.length} agents ready · simulation`} id={`${active.length} agent siap · simulasi`} />
          </span>
          <h1>
            <Greeting />
          </h1>
          <p>
            <L en="Your AI workforce is ready. Here is what the team is working on." id="Tim AI kamu siap. Ini yang sedang dikerjakan tim." />
          </p>
          <div className="hello__actions">
            <GenerateRun steps={monthlyRun()} />
            <Link href="/team" className="btn btn--secondary">
              <Icon name="team" size={16} />
              <L en="Meet your AI team" id="Kenalan dengan tim AI" />
            </Link>
          </div>
        </div>
        <div className="hello__team" aria-hidden="true">
          {active.slice(0, 6).map((m) => (
            <Avatar key={m.id} name={m.name} hue={m.hue} look={m.look} uniform={m.uniform} image={m.image} size="lg" />
          ))}
        </div>
      </section>

      <Onboarding />

      <SimNotice />

      <div className="kpis">
        <Kpi label={<L en="Active clients" id="Klien aktif" />} value={CLIENTS.filter((c) => c.status === "active").length} hint={<L en={`${CLIENTS.length} clients in total`} id={`${CLIENTS.length} klien total`} />} />
        <Kpi label={<L en="Content this month" id="Konten bulan ini" />} value={CONTENT.length} hint={<L en="Publish date in October, all statuses" id="Tayang di bulan Oktober, semua status" />} />
        <Kpi label={<L en="Needs review" id="Perlu review" />} value={pending.length} hint={<L en="AI review + human review" id="Cek AI + review manusia" />} />
        <Kpi label={<L en="Published" id="Tayang" />} value={published.length} hint={<L en="Published by your team" id="Dipublish oleh tim kamu" />} />
      </div>

      <div className="section-head">
        <div>
          <h2>
            <L en="Meet your AI team" id="Kenalan dengan tim AI kamu" />
          </h2>
          <p>
            <L en="Specialized AI agents working together to create and manage your marketing content." id="Agent AI dengan keahlian berbeda yang bekerja bersama membuat dan mengelola konten marketing kamu." />
          </p>
        </div>
        <Link href="/team" className="link">
          <L en={`View all ${team.length} agents`} id={`Lihat ${team.length} agent`} />
        </Link>
      </div>
      <div className="team-grid team-grid--row">
        {featured.map((m) => (
          <MemberCard key={m.id} m={m} compact />
        ))}
      </div>

      <div className="grid-2 mt" style={{ marginTop: 24 }}>
        <div className="stack">
          <Card title={<L en="Recent projects" id="Proyek terbaru" />} action={<Link href="/projects" className="link"><L en="View all" id="Lihat semua" /></Link>} flush>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th><L en="Client" id="Klien" /></th>
                    <th><L en="Project" id="Proyek" /></th>
                    <th><L en="Progress" id="Progres" /></th>
                    <th><L en="Due" id="Tenggat" /></th>
                  </tr>
                </thead>
                <tbody>
                  {PROJECTS.map((p) => {
                    const items = CONTENT.filter((c) => c.project === p.id);
                    const done = items.filter((c) => ["approved", "scheduled", "published"].includes(c.status)).length;
                    return (
                      <tr key={p.id}>
                        <td className="cell-strong">{clientName(p.client)}</td>
                        <td>{p.name}</td>
                        <td><Progress value={done} total={items.length} /></td>
                        <td className="nowrap muted"><D iso={p.due} /></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Card>
          <Card title={<L en="In review" id="Sedang direview" />} action={<Link href="/content" className="link"><L en="Open content" id="Buka konten" /></Link>} flush>
            <ul className="list">
              {pending.map((c) => {
                const m = getMember(c.agent)!;
                return (
                  <li key={c.id}>
                    <Avatar name={m.name} hue={m.hue} look={m.look} uniform={m.uniform} image={m.image} size="sm" />
                    <div className="list__main">
                      <span className="list__title">{c.title}</span>
                      <span className="list__sub">{c.type} · {clientName(c.client)}</span>
                    </div>
                    <Level level={c.level} />
                    <StatusBadge status={c.status} />
                  </li>
                );
              })}
            </ul>
          </Card>
        </div>
        <div className="stack">
          <Card title={<L en="AI activity" id="Aktivitas AI" />} action={<span className="badge badge--warning"><L en="Simulation" id="Simulasi" /></span>} flush>
            <ul className="list">
              {ACTIVITY.map((a) => {
                const m = getMember(a.agent)!;
                return (
                  <li key={a.en}>
                    <Avatar name={m.name} hue={m.hue} look={m.look} uniform={m.uniform} image={m.image} size="sm" decorative />
                    <div className="list__main">
                      <span className="list__title" style={{ whiteSpace: "normal" }}>
                        {m.name} · <L en={a.en} id={a.id} />
                      </span>
                      <span className="list__sub">{a.when === "now" ? <L en="Now" id="Sekarang" /> : <L en={`${a.when} ago`} id={`${a.when} lalu`} />}</span>
                    </div>
                    {a.state === "working" ? (
                      <span className="activity__state activity__state--working"><i /> <L en="Working" id="Bekerja" /></span>
                    ) : (
                      <span className="activity__state activity__state--done"><Icon name="check" size={14} /> <L en="Done" id="Selesai" /></span>
                    )}
                  </li>
                );
              })}
            </ul>
          </Card>
          <Card title={<L en="Upcoming content" id="Jadwal tayang" />} action={<Link href="/calendar" className="link"><L en="Calendar" id="Kalender" /></Link>} flush>
            <ul className="list">
              {upcoming.map((c) => (
                <li key={c.id}>
                  <span className="date-chip">
                    <b>{Number(c.date.slice(8))}</b>
                    <span><D iso={c.date} month /></span>
                  </span>
                  <div className="list__main">
                    <span className="list__title">{c.title}</span>
                    <span className="list__sub">{c.type} · {clientName(c.client)}</span>
                  </div>
                </li>
              ))}
            </ul>
          </Card>
        </div>
      </div>
    </>
  );
}
