"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Card } from "./ui";
import { Notice } from "./WorkflowUi";
import { api, errorText } from "../lib/auth";
import { ACTIVE_JOB, JOB_ERROR, JOB_STATUS, JOB_TONE, type AiJob } from "../lib/ai";
import { L, useL, useLang } from "../lib/i18n";
import { formatDate, type Page } from "../lib/workflow";

const POLL_MS = 3000;

/**
 * Tombol "Buat draft dengan AI" + status job terakhir request ini. Job dikerjakan worker di belakang; panel ini
 * memeriksa status tiap 3 detik selama job antre/berjalan, lalu memuat ulang draft saat selesai.
 * Hasil AI selalu draft: tetap direview manusia dan disetujui klien. Tidak ada publish.
 */
export default function AiPanel({ requestId, canAsk, selfServe = false, onJobs, onDraft }: {
  requestId: number;
  canAsk: boolean;
  selfServe?: boolean;
  onJobs: (jobs: AiJob[]) => void;
  onDraft: () => void;
}) {
  const tr = useL();
  const { lang } = useLang();
  const [jobs, setJobs] = useState<AiJob[]>([]);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const wasActive = useRef(false);
  const callbacks = useRef({ onJobs, onDraft });
  useEffect(() => { callbacks.current = { onJobs, onDraft }; }, [onJobs, onDraft]);

  const load = useCallback(async () => {
    const r = await api<Page<AiJob>>(`ai-jobs?request_id=${requestId}&limit=20`);
    if (!r.ok) return;
    setJobs(r.data.items);
    callbacks.current.onJobs(r.data.items);
    const active = r.data.items.some((j) => ACTIVE_JOB.has(j.status));
    if (wasActive.current && !active) callbacks.current.onDraft(); // job baru selesai: draft (atau kegagalan) tampil
    wasActive.current = active;
  }, [requestId]);

  useEffect(() => { load(); }, [load]);
  const latest = jobs[0];
  const active = latest && ACTIVE_JOB.has(latest.status);
  useEffect(() => {
    if (!active) return;
    const t = setInterval(load, POLL_MS);
    return () => clearInterval(t);
  }, [active, load]);

  async function ask() {
    setBusy(true);
    setMsg(null);
    const r = await api<AiJob>(`requests/${requestId}/ai-drafts`, { method: "POST", body: {} });
    setBusy(false);
    if (!r.ok) return setMsg({ ok: false, text: errorText(r, lang) });
    wasActive.current = true;
    load();
  }

  async function cancel(job: AiJob) {
    const r = await api<AiJob>(`ai-jobs/${job.id}/cancel`, { method: "POST", body: {} });
    if (!r.ok) setMsg({ ok: false, text: errorText(r, lang) });
    load();
  }

  if (!canAsk && !latest) return null;
  const say = (pair: [string, string] | undefined, fallback: string) => (pair ? pair[lang === "id" ? 1 : 0] : fallback);

  return (
    <Card title={<L en="Draft with AI" id="Draft dengan AI" />}>
      {latest && (
        <div className="ai-job" aria-live="polite">
          <span className={`badge badge--${JOB_TONE[latest.status]}`}>{say(JOB_STATUS[latest.status], latest.status)}</span>
          <span className="muted"> {latest.agent_id} · {formatDate(latest.created_at, lang)}</span>
          {latest.status === "running" && latest.attempts > 1 && (
            <span className="muted"> · {tr(`attempt ${latest.attempts} of ${latest.max_attempts}`, `percobaan ${latest.attempts} dari ${latest.max_attempts}`)}</span>
          )}
          {latest.error_code && latest.status !== "cancelled" && (
            <p className="auth-error wf-hint">{say(JOB_ERROR[latest.error_code], latest.error_code)}</p>
          )}
          {latest.status === "queued" && canAsk && (
            <button type="button" className="btn btn--secondary btn--sm" onClick={() => cancel(latest)}>{tr("Cancel", "Batalkan")}</button>
          )}
        </div>
      )}
      {canAsk && !active && (
        <button type="button" className="btn btn--primary" onClick={ask} disabled={busy}>
          {latest ? tr("Ask AI for a new version", "Minta AI menulis versi baru") : tr("Draft with AI", "Buat draft dengan AI")}
        </button>
      )}
      <Notice msg={msg} />
      <p className="muted wf-hint">
        {selfServe ? (
          <L
            en="The agent only uses facts from your business Brain and checks every claim against them. Claims without a fact are marked RISK and lock approval. Each draft uses the credits shown on the Credits page; failed jobs give credits back."
            id="Agen hanya memakai fakta dari Brain bisnis kamu dan mengecek setiap klaim ke fakta itu. Klaim tanpa fakta ditandai RISK dan mengunci persetujuan. Setiap draft memakai kredit sesuai halaman Kredit; job gagal = kredit kembali."
          />
        ) : (
        <L
          en="The AI only uses facts the client approved, and checks every claim against them. Claims without a fact are marked RISK and lock approval. You and an independent reviewer still read the whole draft, and the person who asked the AI can't approve it."
          id="AI hanya memakai fakta yang disetujui klien dan mengecek setiap klaim ke fakta itu. Klaim tanpa fakta ditandai RISK dan mengunci approval. Seluruh draft tetap dibaca kamu dan reviewer independen, dan orang yang meminta AI tidak bisa meng-approve-nya."
        />
        )}
      </p>
    </Card>
  );
}
