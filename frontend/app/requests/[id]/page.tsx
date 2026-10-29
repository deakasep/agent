"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Card, PageHeader } from "../../../components/ui";
import AiPanel from "../../../components/AiPanel";
import { Field, Notice, RefLink, SessionGate, StatusPill } from "../../../components/WorkflowUi";
import { draftAuthor, type AiJob } from "../../../lib/ai";
import { api, errorText, type Me } from "../../../lib/auth";
import { L, useL, useLang } from "../../../lib/i18n";
import {
  AGENCY_WRITERS, CLAIM_CATEGORIES, CONTENT_FLAGS, DECISIONS, EVIDENCE_LABELS, FACTUAL, FLAG_LABEL, FLAG_LEVEL, FLAG_SOURCE_LABEL,
  LEVELS, QA_GATES, QA_RESULTS, REF_RE, SENIOR, formatDate, isSelfServeOwner, levelReason, memberFor, roleFor, useClients, useSession,
  type Approval, type Claim, type ContentFlag, type Draft, type DraftSummary, type Fact, type FactSheet, type FactSheetDetail, type Page, type QARecord, type WfRequest,
} from "../../../lib/workflow";

type Msg = { ok: boolean; text: string } | null;
const OPEN = new Set(["open", "in_progress"]);

export default function RequestDetail() {
  const params = useParams<{ id: string }>();
  const id = Number(params?.id);
  const tr = useL();
  const { lang } = useLang();
  const { me, state } = useSession();
  const clients = useClients(state === "ready");
  const [req, setReq] = useState<WfRequest | null>(null);
  const [drafts, setDrafts] = useState<DraftSummary[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [qa, setQa] = useState<QARecord[]>([]);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [latestDraft, setLatestDraft] = useState<Draft | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [saved, setSaved] = useState<Msg>(null);
  const [error, setError] = useState("");
  const [aiJobs, setAiJobs] = useState<AiJob[]>([]);

  const loadDraft = useCallback(async (draftId: number) => {
    setSelected(draftId);
    const [d, q, a] = await Promise.all([
      api<Draft>(`drafts/${draftId}`),
      api<Page<QARecord>>(`qa-records?draft_id=${draftId}&limit=100`),
      api<Page<Approval>>(`approvals?draft_id=${draftId}&limit=100`),
    ]);
    if (d.ok) setDraft(d.data);
    if (q.ok) setQa(q.data.items);
    if (a.ok) setApprovals(a.data.items);
  }, []);

  const load = useCallback(async (focusLatest = false) => {
    const r = await api<WfRequest>(`requests/${id}`);
    if (!r.ok) return setError(errorText(r, lang));
    setReq(r.data);
    const d = await api<Page<DraftSummary>>(`drafts?request_id=${id}&limit=100`);
    if (!d.ok) return setError(errorText(d, lang));
    const list = [...d.data.items].sort((x, y) => y.version - x.version);
    setDrafts(list);
    // Versi baru selalu disusun dari versi TERBARU (bukan versi yang sedang dilihat).
    const newest = list[0] ? await api<Draft>(`drafts/${list[0].id}`) : null;
    setLatestDraft(newest && newest.ok ? newest.data : null);
    setLoaded(true);
    const target = focusLatest || selected === null ? list[0]?.id : selected;
    if (target) await loadDraft(target);
  }, [id, lang, loadDraft, selected]);

  useEffect(() => {
    document.title = `${tr("Request", "Permintaan")} #${id} · CLAU AI`;
    if (state === "ready" && Number.isInteger(id) && id > 0) load(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state, id]);

  const header = (
    <PageHeader
      title={<><L en="Request" id="Permintaan" /> #{Number.isInteger(id) ? id : "?"}</>}
      subtitle={<Link className="link" href="/requests">← <L en="All requests" id="Semua permintaan" /></Link>}
    />
  );
  if (state !== "ready" || !me) return <>{header}<SessionGate state={state} /></>;
  if (!req) return <>{header}{error && <p className="auth-notice auth-notice--error" role="alert">{error}</p>}</>;

  const role = roleFor(me, req.client_code);
  const open = OPEN.has(req.status);
  const latest = drafts[0];
  // Draft agent: "pembuat" = peminta job AI (rule 08; database menolak review/approval oleh peminta).
  const author = draft ? draftAuthor(draft, aiJobs) : null;
  // Langganan mandiri (0.13.0): pemilik usaha meminta draft AI dan menyetujuinya sendiri (AI-CONSTITUTION §11).
  const selfServe = isSelfServeOwner(me, clients.find((c) => c.client_code === req.client_code));

  return (
    <>
      {header}
      {error && <p className="auth-notice auth-notice--error" role="alert">{error}</p>}
      <Card title={<>{req.intent} · {req.client_code}</>} action={<StatusPill status={req.status} />}>
        <p className="wf-text">{req.text}</p>
        <dl className="kv wf-kv">
          <div><dt>{tr("Priority", "Prioritas")}</dt><dd>{req.priority} ({req.priority_score})</dd></div>
          <div><dt>{tr("Deadline", "Tenggat")}</dt><dd>{formatDate(req.deadline, lang)}</dd></div>
          <div>
            <dt>{tr("Min. approval", "Approval min.")}</dt>
            <dd>{req.approval_min}<span className="muted"> · {tr("raised by the draft's content", "naik sesuai isi draft")}</span></dd>
          </div>
          <div><dt>Agent</dt><dd>{req.agent ?? "—"}</dd></div>
          {req.review_rating != null && <div><dt>{tr("Review rating", "Rating review")}</dt><dd>{"★".repeat(req.review_rating)} ({req.review_rating})</dd></div>}
          {req.source_draft_id != null && <div><dt>{tr("Source draft", "Draft asal")}</dt><dd>#{req.source_draft_id}</dd></div>}
        </dl>
        {!open && <p className="muted wf-hint">{tr("This request is finished. Changes need a new request.", "Permintaan ini sudah selesai. Perubahan perlu permintaan baru.")}</p>}
      </Card>

      <div className="users-layout mt">
        <div className="stack">
          <Card
            title={<L en="Drafts" id="Draft" />}
            action={drafts.length > 1 && (
              <select aria-label={tr("Draft version", "Versi draft")} className="wf-filter" value={selected ?? ""} onChange={(e) => loadDraft(Number(e.target.value))}>
                {drafts.map((d) => <option key={d.id} value={d.id}>v{d.version}{d.latest ? ` · ${tr("latest", "terbaru")}` : ""}</option>)}
              </select>
            )}
          >
            {!draft ? (
              <p className="muted">{tr("No draft yet.", "Belum ada draft.")}</p>
            ) : (
              <DraftView draft={draft} lang={lang} author={author} canAdd={open && AGENCY_WRITERS.has(role)} canRemove={open && SENIOR.has(role)} onChange={() => load()} />
            )}
          </Card>

          {draft && (
            <Card title={<L en="Reviews (QA)" id="Review (QA)" />} flush>
              <Records rows={qa.map((q) => [q.gate, q.result, `${q.reviewer_role}${q.independent ? ` · ${tr("independent", "independen")}` : ""}`, formatDate(q.created_at, lang)])}
                head={[tr("Gate", "Gate"), tr("Result", "Hasil"), tr("By", "Oleh"), tr("When", "Waktu")]} empty={tr("No reviews yet.", "Belum ada review.")} statusCol={1} />
            </Card>
          )}

          {draft && (
            <Card title={<L en="Decisions" id="Keputusan" />} flush>
              <Records rows={approvals.map((a) => [a.level, a.decision, a.approver_role, <RefLink key="r" value={a.channel_ref} />, formatDate(a.decided_at, lang)])}
                head={[tr("Level", "Level"), tr("Decision", "Keputusan"), tr("By", "Oleh"), tr("Written evidence", "Bukti tertulis"), tr("When", "Waktu")]}
                empty={tr("No decisions yet.", "Belum ada keputusan.")} statusCol={1} />
            </Card>
          )}
        </div>

        <div className="stack">
          <AiPanel requestId={req.id} canAsk={open && (AGENCY_WRITERS.has(role) || selfServe)} selfServe={selfServe} onJobs={setAiJobs} onDraft={() => load(true)} />
          {open && draft && draft.id === latest?.id && <DecisionForm key={draft.id} me={me} req={req} draft={draft} author={author} selfServe={selfServe} onDone={() => load(true)} />}
          {open && draft && AGENCY_WRITERS.has(role) && <QAForm key={draft.id} me={me} role={role} draft={draft} author={author} onDone={() => loadDraft(draft.id)} />}
          {/* Pesan di luar form: form dipasang ulang dari versi terbaru setelah tersimpan. */}
          <Notice msg={saved} />
          {open && loaded && AGENCY_WRITERS.has(role) && (
            <DraftForm key={`${latestDraft?.id ?? "new"}:${(latestDraft?.content_flags ?? []).map((f) => f.flag).join(",")}`} req={req} previous={latestDraft} onDone={(v) => { setSaved({ ok: true, text: tr(`Saved as version ${v}.`, `Tersimpan sebagai versi ${v}.`) }); load(true); }} />
          )}
          <p className="muted wf-hint">
            <L en="CLAU never publishes. After final approval, your team publishes in the official apps." id="CLAU tidak pernah mempublish. Setelah disetujui, tim kamu mempublish di aplikasi resmi." />
          </p>
        </div>
      </div>
    </>
  );
}

function DraftView({ draft, lang, author, canAdd, canRemove, onChange }: {
  draft: Draft; lang: string; author: number | null; canAdd: boolean; canRemove: boolean; onChange: () => void;
}) {
  const tr = useL();
  // Nilai fakta yang dijawab klien, berdampingan dengan klaim: reviewer & approver membandingkan teks klaim dengan
  // nilai yang benar (termasuk koreksi klien), bukan hanya fact key.
  const [facts, setFacts] = useState<Record<string, Fact>>({});
  const [sheet, setSheet] = useState<FactSheetDetail | null>(null);
  useEffect(() => {
    setFacts({});
    setSheet(null);
    if (!draft.fact_sheet_id) return;
    api<FactSheetDetail>(`fact-sheets/${draft.fact_sheet_id}`).then((r) => {
      if (!r.ok) return;
      setSheet(r.data);
      setFacts(Object.fromEntries(r.data.facts.map((f) => [f.fact_key, f])));
    });
  }, [draft.fact_sheet_id]);
  return (
    <>
      <div className="wf-meta">
        <span className="badge badge--neutral">v{draft.version}</span>
        <span className={`badge badge--${draft.mode === "SIMULASI" ? "warning" : "info"}`}>{draft.mode}</span>
        {draft.agent_id && draft.created_by === null && <span className="badge badge--info">{tr("Written by AI", "Ditulis AI")} · {draft.agent_id}</span>}
        <span className="muted">{draft.skill} · {formatDate(draft.created_at, lang)}</span>
        {draft.fact_sheet_id && <Link className="link" href={`/fact-sheets/${draft.fact_sheet_id}`}>{tr("Fact sheet", "Fact sheet")} #{draft.fact_sheet_id}</Link>}
      </div>
      {draft.agent_id && draft.created_by === null && (
        <p className="muted wf-hint">
          {tr("AI draft: read the whole text, not only the claims below. The AI checked only the claims it reported.", "Draft AI: baca seluruh teks, bukan hanya klaim di bawah. AI hanya mengecek klaim yang ia laporkan.")}
        </p>
      )}
      <pre className="wf-content">{draft.content}</pre>
      <ContentLevel draft={draft} canAdd={canAdd} canRemove={canRemove} onChange={onChange} />
      {draft.claims.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>{tr("Claim", "Klaim")}</th><th>{tr("Category", "Kategori")}</th><th>{tr("Evidence", "Bukti")}</th><th>{tr("Client's answer", "Jawaban klien")}</th></tr></thead>
            <tbody>
              {draft.claims.map((c) => {
                const f = c.fact_key ? facts[c.fact_key] : undefined;
                return (
                  <tr key={c.id} className={c.evidence_label === "RISK" ? "wf-risk" : undefined}>
                    <td>{c.text}</td>
                    <td>{c.category}</td>
                    <td>{c.evidence_label}</td>
                    <td>
                      {!c.fact_key ? "—" : (
                        <>
                          <code>{c.fact_key}</code>
                          {f ? (
                            <div className="wf-hint"><strong>{f.current_value}</strong> <StatusPill status={f.status} /></div>
                          ) : (
                            <div className="wf-hint auth-error">{tr("Not in the cited fact sheet", "Tidak ada di fact sheet yang dirujuk")}</div>
                          )}
                        </>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {sheet && sheet.status !== "approved" && (
        <p className="wf-hint auth-error">{tr("The cited fact sheet isn't approved by the client yet.", "Fact sheet yang dirujuk belum disetujui klien.")}</p>
      )}
    </>
  );
}

function Records({ rows, head, empty, statusCol }: { rows: ReactNode[][]; head: string[]; empty: string; statusCol: number }) {
  if (rows.length === 0) return <p className="muted wf-empty">{empty}</p>;
  return (
    <div className="table-wrap">
      <table className="table">
        <thead><tr>{head.map((h) => <th key={h}>{h}</th>)}</tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>{r.map((cell, j) => <td key={j}>{j === statusCol && typeof cell === "string" ? <StatusPill status={cell} /> : cell}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DecisionForm({ me, req, draft, author, selfServe, onDone }: { me: Me; req: WfRequest; draft: Draft; author: number | null; selfServe: boolean; onDone: () => void }) {
  const tr = useL();
  const { lang } = useLang();
  const member = memberFor(me, req.client_code);
  const role = member?.role ?? "";
  const max = LEVELS.indexOf((member?.max_level ?? "L1") as (typeof LEVELS)[number]);
  // Level minimum dihitung database (clau_draft_min_level: intent, klaim fakta, draft AI, penanda isi, draft asal).
  // Cadangan bila backend lama: aturan 0.9.0.
  const agentReal = draft.created_by === null && !!draft.agent_id && draft.mode === "NYATA";
  const minimum = draft.min_level
    ? LEVELS.indexOf(draft.min_level as (typeof LEVELS)[number])
    : Math.max(LEVELS.indexOf(req.approval_min as (typeof LEVELS)[number]), draft.claims.some((c) => c.fact_key) || agentReal ? 1 : 0);
  const levels = LEVELS.filter((_, i) => i >= minimum && i <= max);
  const [level, setLevel] = useState<string>(levels[0] ?? "");
  const [decision, setDecision] = useState<string>(draft.mode === "SIMULASI" ? "Revise" : "Approved");
  const [ref, setRef] = useState("");
  const [msg, setMsg] = useState<Msg>(null);
  if (!SENIOR.has(role) && role !== "client_approver") return null;
  // Draft agen di langganan mandiri: pembuatnya agen AI, pemilik usaha yang memutuskan.
  if (author === me.user.id && !(selfServe && draft.created_by === null))
    return <Card><p className="muted">{draft.created_by === null
      ? tr("You asked the AI for this draft, so someone else must decide on it.", "Kamu yang meminta draft AI ini, jadi orang lain yang memutuskan.")
      : tr("You wrote this draft, so someone else must decide on it.", "Kamu yang menulis draft ini, jadi orang lain yang memutuskan.")}</p></Card>;
  const agency = SENIOR.has(role);
  const needsRef = agency && decision === "Approved";

  async function submit(e: FormEvent) {
    e.preventDefault();
    const r = await api<Approval>("approvals", { method: "POST", body: { draft_id: draft.id, level, decision, ...(ref.trim() ? { channel_ref: ref.trim() } : {}) } });
    if (r.ok) {
      setMsg({ ok: true, text: tr("Decision recorded.", "Keputusan tercatat.") });
      setRef("");
      onDone();
    } else setMsg({ ok: false, text: errorText(r, lang) });
  }

  if (levels.length === 0)
    return <Card><p className="muted">{tr(`This draft needs ${LEVELS[minimum]} or higher, above your limit.`, `Draft ini butuh ${LEVELS[minimum]} atau lebih, di atas batasmu.`)}</p></Card>;
  return (
    <Card title={<L en="Decide" id="Putuskan" />}>
      <form onSubmit={submit} className="auth-form">
        <div className="wf-row">
          <Field id="ap-level" label={tr("Level", "Level")}>
            <select id="ap-level" value={level} onChange={(e) => setLevel(e.target.value)}>
              {levels.map((l) => <option key={l} value={l}>{l}</option>)}
            </select>
          </Field>
          <Field id="ap-decision" label={tr("Decision", "Keputusan")}>
            <select id="ap-decision" value={decision} onChange={(e) => setDecision(e.target.value)}>
              {DECISIONS.filter((d) => !(d === "Approved" && draft.mode === "SIMULASI")).map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
          </Field>
        </div>
        {agency && (
          <Field id="ap-ref" label={tr("Client's written approval (link)", "Bukti persetujuan tertulis klien (link)")}
            hint={tr("You record the client's decision; link the archived email or message (https://, mailto:, workspace://).", "Kamu mencatat keputusan klien; tautkan email/pesan yang diarsipkan (https://, mailto:, workspace://).")}>
            <input id="ap-ref" value={ref} onChange={(e) => setRef(e.target.value)} required={needsRef} maxLength={500} placeholder="https://" />
          </Field>
        )}
        {(level === "L2" || level === "L3") && decision === "Approved" && (
          <p className="muted wf-hint">{selfServe
            ? tr("Read the whole draft first: your approval is the final human check. Claims marked RISK must be fixed or added to your business Brain.", "Baca seluruh draft dulu: persetujuanmu adalah pemeriksaan manusia terakhir. Klaim bertanda RISK harus diperbaiki atau ditambahkan ke Brain bisnis.")
            : tr("L2/L3 needs a passed independent claim verification on this draft.", "L2/L3 butuh claim verification independen yang lulus di draft ini.")}</p>
        )}
        <Notice msg={msg} />
        <button type="submit" className="btn btn--primary" disabled={!level || (needsRef && !REF_RE.test(ref.trim()))}>{tr("Record decision", "Catat keputusan")}</button>
      </form>
    </Card>
  );
}

function QAForm({ me, role, draft, author, onDone }: { me: Me; role: string; draft: Draft; author: number | null; onDone: () => void }) {
  const tr = useL();
  const { lang } = useLang();
  const [gate, setGate] = useState<string>("claim-verification");
  const [result, setResult] = useState<string>("Pass");
  const canIndependent = SENIOR.has(role) && author !== me.user.id;
  const [independent, setIndependent] = useState(canIndependent);
  const [msg, setMsg] = useState<Msg>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const r = await api<QARecord>("qa-records", { method: "POST", body: { draft_id: draft.id, gate, result, independent: independent && canIndependent } });
    if (r.ok) {
      setMsg({ ok: true, text: tr("Review recorded.", "Review tercatat.") });
      onDone();
    } else setMsg({ ok: false, text: errorText(r, lang) });
  }

  return (
    <Card title={<L en="Record a review" id="Catat review" />}>
      <form onSubmit={submit} className="auth-form">
        <div className="wf-row">
          <Field id="qa-gate" label="Gate">
            <select id="qa-gate" value={gate} onChange={(e) => setGate(e.target.value)}>
              {QA_GATES.map((g) => <option key={g} value={g}>{g}</option>)}
            </select>
          </Field>
          <Field id="qa-result" label={tr("Result", "Hasil")}>
            <select id="qa-result" value={result} onChange={(e) => setResult(e.target.value)}>
              {QA_RESULTS.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </Field>
        </div>
        <label className="wf-check">
          <input type="checkbox" checked={independent && canIndependent} disabled={!canIndependent} onChange={(e) => setIndependent(e.target.checked)} />
          {tr("Independent review (not the author)", "Review independen (bukan pembuat)")}
        </label>
        {!canIndependent && <span className="muted wf-hint">{tr("Independent reviews are by the owner or a content lead who didn't write the draft (or ask the AI for it).", "Review independen oleh owner atau content lead yang tidak menulis draft (atau meminta AI menulisnya).")}</span>}
        <Notice msg={msg} />
        <button type="submit" className="btn btn--secondary">{tr("Save review", "Simpan review")}</button>
      </form>
    </Card>
  );
}

const EMPTY_CLAIM: Claim = { text: "", category: "experience", evidence_label: "ASSUMPTION", fact_key: "" };

function DraftForm({ req, previous, onDone }: { req: WfRequest; previous: Draft | null; onDone: (version: number) => void }) {
  const tr = useL();
  const { lang } = useLang();
  const [content, setContent] = useState(previous?.content ?? "");
  const [claims, setClaims] = useState<Claim[]>(previous?.claims.map(({ id: _id, ...c }) => ({ ...c, fact_key: c.fact_key ?? "" })) ?? []);
  const [sheets, setSheets] = useState<FactSheet[]>([]);
  const [sheetId, setSheetId] = useState<string>("");
  const [keys, setKeys] = useState<string[]>([]);
  // Penanda isi konten (API 0.10.0): wajib dipilih, atau dinyatakan tidak ada (keputusan owner K5). Penanda versi
  // sebelumnya diwarisi server; di sini ditampilkan sebagai sudah tercentang.
  const inherited = new Set((previous?.content_flags ?? []).filter((f) => f.source !== "server").map((f) => f.flag));
  const [picked, setPicked] = useState<Set<ContentFlag>>(new Set(inherited));
  const [noneConfirmed, setNoneConfirmed] = useState(false);
  const [msg, setMsg] = useState<Msg>(null);

  useEffect(() => {
    api<Page<FactSheet>>(`fact-sheets?client_code=${req.client_code}&approved=true&limit=100`).then((r) => {
      if (!r.ok) return;
      // Default = versi disetujui terbaru (versi lama yang sudah digantikan tidak bisa di-approve).
      const list = [...r.data.items].sort((a, b) => b.version - a.version);
      setSheets(list);
      if (list[0]) setSheetId(String(list[0].id));
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [req.client_code]);
  useEffect(() => {
    if (!sheetId) return setKeys([]);
    api<FactSheetDetail>(`fact-sheets/${sheetId}`).then((r) => r.ok && setKeys(r.data.facts.map((f) => f.fact_key)));
  }, [sheetId]);

  function setClaim(i: number, patch: Partial<Claim>) {
    setClaims((cs) => cs.map((c, j) => (j === i ? { ...c, ...patch } : c)));
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    const body = {
      request_id: req.id,
      fact_sheet_id: sheetId ? Number(sheetId) : null,
      content,
      content_flags: [...picked],
      claims: claims.map((c) => ({
        text: c.text, category: c.category, evidence_label: c.evidence_label,
        fact_key: (FACTUAL as readonly string[]).includes(c.category) ? c.fact_key || null : null,
        ...(c.evidence_label === "DATA FINAL" ? { source: c.source || null, source_date: c.source_date || null } : {}),
      })),
    };
    const r = await api<Draft>("drafts", { method: "POST", body });
    if (r.ok) onDone(r.data.version);
    else setMsg({ ok: false, text: errorText(r, lang) });
  }

  return (
    <Card title={previous ? <L en="Save a new version" id="Simpan versi baru" /> : <L en="Write the first draft" id="Tulis draft pertama" />}>
      <form onSubmit={submit} className="auth-form">
        <Field id="dr-content" label={tr("Content", "Isi")}>
          <textarea id="dr-content" value={content} onChange={(e) => setContent(e.target.value)} required maxLength={10000} rows={8} />
        </Field>
        <Field id="dr-sheet" label={tr("Approved fact sheet", "Fact sheet yang disetujui")}
          hint={sheets.length === 0 ? tr("No approved fact sheet for this client yet: factual claims can't be approved.", "Belum ada fact sheet yang disetujui untuk klien ini: klaim fakta belum bisa disetujui.") : undefined}>
          <select id="dr-sheet" value={sheetId} onChange={(e) => setSheetId(e.target.value)}>
            <option value="">{tr("None", "Tidak ada")}</option>
            {sheets.map((s) => <option key={s.id} value={s.id}>v{s.version} · {formatDate(s.approved_at, lang)}</option>)}
          </select>
        </Field>
        <fieldset className="wf-claims">
          <legend>{tr("Claims in this draft", "Klaim di draft ini")}</legend>
          <datalist id="dr-keys">{keys.map((k) => <option key={k} value={k} />)}</datalist>
          {claims.map((c, i) => {
            const factual = (FACTUAL as readonly string[]).includes(c.category);
            return (
              <div key={i} className="wf-claim">
                <input aria-label={tr(`Claim ${i + 1}`, `Klaim ${i + 1}`)} value={c.text} onChange={(e) => setClaim(i, { text: e.target.value })} required maxLength={300} placeholder={tr("Claim as written", "Klaim seperti ditulis")} />
                <select aria-label={tr("Category", "Kategori")} value={c.category} onChange={(e) => setClaim(i, { category: e.target.value })}>
                  {CLAIM_CATEGORIES.map((k) => <option key={k} value={k}>{k}</option>)}
                </select>
                <select aria-label={tr("Evidence", "Bukti")} value={c.evidence_label} onChange={(e) => setClaim(i, { evidence_label: e.target.value })}>
                  {EVIDENCE_LABELS.map((k) => <option key={k} value={k}>{k}</option>)}
                </select>
                {factual && (
                  <input aria-label="Fact key" list="dr-keys" value={c.fact_key ?? ""} onChange={(e) => setClaim(i, { fact_key: e.target.value.trim() })} required placeholder={`${c.category}.…`} />
                )}
                {c.evidence_label === "DATA FINAL" && (
                  <>
                    <input aria-label={tr("Source", "Sumber")} value={c.source ?? ""} onChange={(e) => setClaim(i, { source: e.target.value })} required maxLength={300} placeholder={tr("Source", "Sumber")} />
                    <input aria-label={tr("Source date", "Tanggal sumber")} type="date" value={c.source_date ?? ""} onChange={(e) => setClaim(i, { source_date: e.target.value })} required />
                  </>
                )}
                <button type="button" className="btn btn--secondary btn--sm" onClick={() => setClaims((cs) => cs.filter((_, j) => j !== i))}>{tr("Remove", "Hapus")}</button>
              </div>
            );
          })}
          {claims.length < 30 && (
            <button type="button" className="btn btn--secondary btn--sm" onClick={() => setClaims((cs) => [...cs, { ...EMPTY_CLAIM }])}>{tr("Add claim", "Tambah klaim")}</button>
          )}
          <p className="muted wf-hint">{tr("Facts (facility, price, capacity, …) need a fact key from the client's approved fact sheet. Impressions use “experience”.", "Fakta (fasilitas, harga, kapasitas, …) wajib fact key dari fact sheet klien yang disetujui. Kesan memakai “experience”.")}</p>
        </fieldset>
        <fieldset className="wf-claims">
          <legend>{tr("What does this content contain?", "Isi konten ini memuat apa?")}</legend>
          <p className="muted wf-hint">{tr("Each item raises the approval level (Rule 08). The system also detects prices and religious/cultural words by itself.", "Setiap pilihan menaikkan level approval (Rule 08). Sistem juga mendeteksi harga dan kata agama/adat sendiri.")}</p>
          {CONTENT_FLAGS.map((f) => (
            <label key={f} className="wf-check">
              <input type="checkbox" checked={picked.has(f)} disabled={inherited.has(f)}
                onChange={(e) => { setNoneConfirmed(false); setPicked((cur) => { const next = new Set(cur); if (e.target.checked) next.add(f); else next.delete(f); return next; }); }} />
              {FLAG_LABEL[f][lang === "en" ? 0 : 1]} <span className="muted">· {FLAG_LEVEL[f]}</span>
              {inherited.has(f) && <span className="muted"> · {tr("kept from the previous version", "diwarisi dari versi sebelumnya")}</span>}
            </label>
          ))}
          <label className="wf-check">
            <input type="checkbox" checked={noneConfirmed} disabled={picked.size > 0} onChange={(e) => setNoneConfirmed(e.target.checked)} />
            {tr("None of the above (I checked the text and visuals)", "Tidak ada satu pun (sudah saya cek teks dan visualnya)")}
          </label>
        </fieldset>
        <Notice msg={msg} />
        <button type="submit" className="btn btn--primary" disabled={!content.trim() || (picked.size === 0 && !noneConfirmed)}>{tr("Save version", "Simpan versi")}</button>
      </form>
    </Card>
  );
}

function ContentLevel({ draft, canAdd, canRemove, onChange }: { draft: Draft; canAdd: boolean; canRemove: boolean; onChange: () => void }) {
  const tr = useL();
  const { lang } = useLang();
  const en = lang === "en";
  const [adding, setAdding] = useState<string>("");
  const [removing, setRemoving] = useState<ContentFlag | null>(null);
  const [reason, setReason] = useState("");
  const [msg, setMsg] = useState<Msg>(null);
  if (!draft.min_level) return null;
  const active = draft.content_flags ?? [];
  const missing = CONTENT_FLAGS.filter((f) => !active.some((a) => a.flag === f));

  async function add() {
    const r = await api(`drafts/${draft.id}/flags`, { method: "POST", body: { flag: adding } });
    if (r.ok) { setAdding(""); setMsg(null); onChange(); } else setMsg({ ok: false, text: errorText(r, lang) });
  }
  async function remove(e: FormEvent) {
    e.preventDefault();
    if (!removing) return;
    const r = await api(`drafts/${draft.id}/flags/${removing}/remove`, { method: "POST", body: { reason } });
    if (r.ok) { setRemoving(null); setReason(""); setMsg(null); onChange(); } else setMsg({ ok: false, text: errorText(r, lang) });
  }

  return (
    <div className="wf-level">
      <p>
        <strong>{tr("Minimum approval", "Approval minimal")}: {draft.min_level}</strong>
        {draft.min_level_reasons && draft.min_level_reasons.length > 0 && (
          <span className="muted"> · {draft.min_level_reasons.map((x) => `${levelReason(x.rule, en)} (${x.level})`).join(" · ")}</span>
        )}
      </p>
      {active.length > 0 && (
        <ul className="wf-flags">
          {active.map((f) => (
            <li key={f.flag}>
              <span className={`badge badge--${FLAG_LEVEL[f.flag] === "L3" ? "warning" : "info"}`}>{FLAG_LABEL[f.flag][en ? 0 : 1]} · {FLAG_LEVEL[f.flag]}</span>
              <span className="muted"> {FLAG_SOURCE_LABEL[f.source][en ? 0 : 1]}</span>
              {canRemove && f.source !== "server" && (
                <button type="button" className="btn btn--secondary btn--sm" onClick={() => { setRemoving(f.flag); setReason(""); }}>{tr("Remove", "Hapus")}</button>
              )}
            </li>
          ))}
        </ul>
      )}
      {canAdd && missing.length > 0 && (
        <div className="wf-row">
          <select aria-label={tr("Add a content flag", "Tambah penanda isi")} value={adding} onChange={(e) => setAdding(e.target.value)}>
            <option value="">{tr("Add a flag…", "Tambah penanda…")}</option>
            {missing.map((f) => <option key={f} value={f}>{FLAG_LABEL[f][en ? 0 : 1]} · {FLAG_LEVEL[f]}</option>)}
          </select>
          <button type="button" className="btn btn--secondary btn--sm" disabled={!adding} onClick={add}>{tr("Add", "Tambah")}</button>
        </div>
      )}
      {removing && (
        <form onSubmit={remove} className="auth-form">
          <Field id="fl-reason" label={tr(`Why remove “${FLAG_LABEL[removing][0]}”?`, `Kenapa menghapus “${FLAG_LABEL[removing][1]}”?`)}
            hint={tr("Written to the audit log. Automatic flags can't be removed.", "Tercatat di audit log. Penanda otomatis tidak bisa dihapus.")}>
            <input id="fl-reason" value={reason} onChange={(e) => setReason(e.target.value)} minLength={10} maxLength={500} required />
          </Field>
          <div className="wf-row">
            <button type="submit" className="btn btn--primary btn--sm" disabled={reason.trim().length < 10}>{tr("Remove flag", "Hapus penanda")}</button>
            <button type="button" className="btn btn--secondary btn--sm" onClick={() => setRemoving(null)}>{tr("Cancel", "Batal")}</button>
          </div>
        </form>
      )}
      <Notice msg={msg} />
    </div>
  );
}
