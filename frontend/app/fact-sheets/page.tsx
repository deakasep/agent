"use client";

import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";
import { Card, PageHeader } from "../../components/ui";
import { Field, Notice, SessionGate, StatusPill } from "../../components/WorkflowUi";
import { api, errorText, type Me } from "../../lib/auth";
import { L, useL, useLang } from "../../lib/i18n";
import { AGENCY_WRITERS, FACTUAL, FACT_KEY_RE, REF_RE, formatDate, isSelfServeOwner, roleFor, useSession, type Client, type FactSheet, type FactSheetDetail, type Page } from "../../lib/workflow";

type Row = { category: string; slug: string; label: string; value: string };
const EMPTY: Row = { category: "facility", slug: "", label: "", value: "" };

export default function FactSheetsPage() {
  const tr = useL();
  const { lang } = useLang();
  const { me, state } = useSession();
  const [clients, setClients] = useState<Client[]>([]);
  const [data, setData] = useState<Page<FactSheet> | null>(null);
  const [error, setError] = useState("");

  async function load() {
    const r = await api<Page<FactSheet>>("fact-sheets?limit=100");
    if (r.ok) setData(r.data);
    else setError(errorText(r, lang));
  }
  useEffect(() => {
    document.title = `${tr("Fact sheets", "Fact sheet")} · CLAU AI`;
    if (state !== "ready") return;
    api<{ items: Client[] }>("clients").then((r) => r.ok && setClients(r.data.items));
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state]);

  const header = (
    <PageHeader
      title={<L en="Fact sheets" id="Fact sheet" />}
      subtitle={<L en="Facts about each client's business. The client confirms or corrects every fact before content can use it." id="Fakta tentang bisnis setiap klien. Klien mengonfirmasi atau mengoreksi setiap fakta sebelum dipakai di konten." />}
    />
  );
  if (state !== "ready" || !me) return <>{header}<SessionGate state={state} /></>;
  const writable = clients.filter((c) => AGENCY_WRITERS.has(roleFor(me, c.client_code)) || isSelfServeOwner(me, c));

  return (
    <>
      {header}
      {error && <p className="auth-notice auth-notice--error" role="alert">{error}</p>}
      <div className="users-layout">
        <Card title={<L en="All versions" id="Semua versi" />} flush>
          {data && data.items.length === 0 ? (
            <p className="muted wf-empty">{tr("No fact sheets yet.", "Belum ada fact sheet.")}</p>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>{tr("Client", "Klien")}</th>
                    <th>{tr("Version", "Versi")}</th>
                    <th>{tr("Answered", "Dijawab")}</th>
                    <th>{tr("Status", "Status")}</th>
                    <th>{tr("Approved", "Disetujui")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data?.items.map((s) => (
                    <tr key={s.id}>
                      <td><Link className="link cell-strong" href={`/fact-sheets/${s.id}`}>{s.client_code}</Link></td>
                      <td>v{s.version}</td>
                      <td>{s.facts_answered}/{s.facts_total}</td>
                      <td><StatusPill status={s.status} /></td>
                      <td>{formatDate(s.approved_at, lang)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
        {writable.length > 0 && <NewFactSheet me={me} clients={writable} onCreated={load} />}
      </div>
    </>
  );
}

function NewFactSheet({ me, clients, onCreated }: { me: Me; clients: Client[]; onCreated: () => void }) {
  const tr = useL();
  const { lang } = useLang();
  const [client, setClient] = useState(clients[0]?.client_code ?? "");
  const [ref, setRef] = useState("");
  const [rows, setRows] = useState<Row[]>([{ ...EMPTY }]);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [created, setCreated] = useState<number | null>(null);

  // Mulai dari versi terakhir klien (fakta tetap, koreksi klien dipakai) agar versi baru tidak diketik ulang.
  async function copyLatest() {
    const list = await api<Page<FactSheet>>(`fact-sheets?client_code=${client}&limit=1`);
    if (!list.ok || !list.data.items[0]) return setMsg({ ok: false, text: tr("No earlier version for this client.", "Belum ada versi sebelumnya untuk klien ini.") });
    const d = await api<FactSheetDetail>(`fact-sheets/${list.data.items[0].id}`);
    if (!d.ok) return setMsg({ ok: false, text: errorText(d, lang) });
    setRef(d.data.document_ref);
    setRows(d.data.facts.map((f) => ({ category: f.category, slug: f.fact_key.slice(f.category.length + 1), label: f.label, value: f.current_value })));
    setMsg(null);
  }

  function setRow(i: number, patch: Partial<Row>) {
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  }
  // Langganan mandiri (0.13.0): pemilik usaha menulis Brain bisnisnya sendiri; langsung berlaku tanpa dokumen sumber.
  const own = isSelfServeOwner(me, clients.find((c) => c.client_code === client));
  const keyOf = (r: Row) => `${r.category}.${r.slug}`;
  const keys = rows.map(keyOf);
  const valid = (own ? !ref.trim() || REF_RE.test(ref.trim()) : REF_RE.test(ref)) && rows.length > 0 && rows.every((r) => FACT_KEY_RE.test(keyOf(r)) && r.label.trim() && r.value.trim()) && new Set(keys).size === keys.length;

  async function submit(e: FormEvent) {
    e.preventDefault();
    const facts = rows.map((r) => ({ fact_key: keyOf(r), category: r.category, label: r.label, value: r.value }));
    const r = await api<FactSheetDetail>("fact-sheets", { method: "POST", body: { client_code: client, ...(ref.trim() ? { document_ref: ref.trim() } : {}), facts } });
    if (r.ok) {
      setCreated(r.data.id);
      setMsg({ ok: true, text: r.data.status === "approved"
        ? tr(`Business Brain v${r.data.version} saved. Your agents use these facts from now on.`, `Brain bisnis v${r.data.version} tersimpan. Agen memakai fakta ini mulai sekarang.`)
        : tr(`Version ${r.data.version} created. Ask the client to confirm each fact.`, `Versi ${r.data.version} dibuat. Minta klien mengonfirmasi setiap fakta.`) });
      setRows([{ ...EMPTY }]);
      onCreated();
    } else setMsg({ ok: false, text: errorText(r, lang) });
  }

  return (
    <Card title={own ? <L en="Business Brain" id="Brain bisnis" /> : <L en="New fact sheet version" id="Versi fact sheet baru" />}>
      <form onSubmit={submit} className="auth-form">
        <Field id="fs-client" label={tr("Client", "Klien")}>
          <select id="fs-client" value={client} onChange={(e) => setClient(e.target.value)}>
            {clients.map((c) => <option key={c.client_code} value={c.client_code}>{c.client_code}</option>)}
          </select>
        </Field>
        <button type="button" className="btn btn--secondary btn--sm" onClick={copyLatest}>{tr("Start from the latest version", "Mulai dari versi terakhir")}</button>
        {own ? (
          <p className="muted wf-hint">{tr("Write the facts about your business that agents may use: prices, facilities, opening hours, location. What you save here counts as confirmed by you and applies right away; a new save creates a new version.", "Tulis fakta usahamu yang boleh dipakai agen: harga, fasilitas, jam buka, lokasi. Yang kamu simpan di sini dianggap sudah kamu konfirmasi dan langsung berlaku; simpan ulang = versi baru.")}</p>
        ) : (
          <Field id="fs-ref" label={tr("Source document (link)", "Dokumen sumber (link)")} hint={tr("Where the full fact sheet lives in the client workspace (https:// or workspace://).", "Lokasi fact sheet lengkap di workspace klien (https:// atau workspace://).")}>
            <input id="fs-ref" value={ref} onChange={(e) => setRef(e.target.value)} required maxLength={500} placeholder="workspace://" />
          </Field>
        )}
        <fieldset className="wf-claims">
          <legend>{tr("Facts", "Fakta")}</legend>
          {rows.map((r, i) => (
            <div key={i} className="wf-claim">
              <select aria-label={tr("Category", "Kategori")} value={r.category} onChange={(e) => setRow(i, { category: e.target.value })}>
                {FACTUAL.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
              <input aria-label={tr("Key", "Kunci")} value={r.slug} onChange={(e) => setRow(i, { slug: e.target.value.toLowerCase().replace(/\s+/g, "-") })} required maxLength={40} placeholder={tr("e.g. pool-private", "mis. pool-private")} />
              <input aria-label={tr("Fact", "Fakta")} value={r.label} onChange={(e) => setRow(i, { label: e.target.value })} required maxLength={200} placeholder={tr("What it is", "Fakta apa")} />
              <input aria-label={tr("Value", "Nilai")} value={r.value} onChange={(e) => setRow(i, { value: e.target.value })} required maxLength={1000} placeholder={tr("Value to confirm", "Nilai yang dikonfirmasi")} />
              <button type="button" className="btn btn--secondary btn--sm" onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))}>{tr("Remove", "Hapus")}</button>
            </div>
          ))}
          {rows.length < 100 && <button type="button" className="btn btn--secondary btn--sm" onClick={() => setRows((rs) => [...rs, { ...EMPTY }])}>{tr("Add fact", "Tambah fakta")}</button>}
          {new Set(keys).size !== keys.length && <p className="auth-error">{tr("Each key can appear once.", "Setiap kunci hanya boleh sekali.")}</p>}
        </fieldset>
        <Notice msg={msg} />
        {created && <Link className="link" href={`/fact-sheets/${created}`}>{tr("Open the new version", "Buka versi baru")} →</Link>}
        <button type="submit" className="btn btn--primary" disabled={!valid}>{own ? tr("Save Brain", "Simpan Brain") : tr("Create version", "Buat versi")}</button>
      </form>
    </Card>
  );
}
