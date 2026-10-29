import Avatar from "../../components/Avatar";
import GenerateRun from "../../components/GenerateRun";
import MemberCard from "../../components/MemberCard";
import { PageHeader } from "../../components/ui";
import { L } from "../../lib/i18n";
import { monthlyRun } from "../../lib/run";
import { CONCEPT_AGENTS, getTeam } from "../../lib/team";

export const metadata = { title: "My AI Team · CLAU" };

export default function TeamPage() {
  const team = getTeam();
  const active = team.filter((m) => m.status === "active");
  const planned = team.filter((m) => m.status === "planned");
  return (
    <>
      <PageHeader
        title={<L en="Meet your AI team" id="Kenalan dengan tim AI kamu" />}
        subtitle={<L en="Specialized AI agents working together to create and manage your marketing content." id="Agent AI dengan keahlian berbeda yang bekerja bersama membuat dan mengelola konten marketing kamu." />}
        actions={<GenerateRun steps={monthlyRun()} />}
      />

      <div className="section-label">
        <L en={`Active · ${active.length}`} id={`Aktif · ${active.length}`} />
      </div>
      <div className="team-grid">
        {active.map((m) => (
          <MemberCard key={m.id} m={m} />
        ))}
      </div>

      <div className="section-label">
        <L en={`Joining soon · ${planned.length}`} id={`Segera bergabung · ${planned.length}`} />
      </div>
      <p className="note" style={{ margin: "-4px 0 12px" }}>
        <L
          en="Voice and boundaries are agreed. These agents start working once their pillar is approved by the owner."
          id="Gaya bahasa dan batasnya sudah disepakati. Agent ini mulai bekerja setelah pilarnya disetujui owner."
        />
      </p>
      <div className="team-grid">
        {planned.map((m) => (
          <MemberCard key={m.id} m={m} />
        ))}
      </div>

      {CONCEPT_AGENTS.length > 0 && (
      <>
      <div className="section-label">
        <L en="Concept roles" id="Peran konsep" />
      </div>
      <p className="note" style={{ margin: "-4px 0 12px" }}>
        <L
          en="Ideas for future roles. They are not designed yet: no persona card, no tests, and they cannot run."
          id="Ide peran di masa depan. Belum dirancang: belum ada kartu persona, belum ada uji, dan tidak bisa dijalankan."
        />
      </p>
      <div className="team-grid">
        {CONCEPT_AGENTS.map((c) => (
          <div key={c.name} className="member member--concept">
            <div className="member__head">
              <Avatar name={c.name} hue="#94A3B8" look={c.look} uniform={c.uniform} image={c.image} size="lg" decorative />
              <div>
                <div className="member__name">{c.name}</div>
                <div className="member__role">
                  <L en={c.role.en} id={c.role.id} />
                </div>
              </div>
            </div>
            <p className="member__desc" style={{ margin: 0 }}>
              <L en={c.tagline.en} id={c.tagline.id} />
            </p>
            <div className="member__foot">
              <span className="who who--concept">
                <L en="Concept" id="Konsep" />
              </span>
            </div>
          </div>
        ))}
      </div>
      </>
      )}
    </>
  );
}
