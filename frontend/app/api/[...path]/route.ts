// Jembatan browser → backend (keputusan VPS #1: tidak ada API publik). Browser hanya bicara ke origin
// frontend; server Next.js meneruskan /api/<path> ke CLAU_BACKEND_URL (jaringan internal / Tailscale).
// Cookie sesi, header CSRF, dan Origin diteruskan apa adanya; backend yang memutuskan semuanya.
import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

// Hanya awalan endpoint yang memang untuk browser (core/shared/api-contracts.md).
const ALLOWED = /^(auth|users|agents|pillars|route|health|requests|drafts|qa-records|approvals|clients|fact-sheets|ai-jobs|ai-usage|ai-budgets|billing)(\/[A-Za-z0-9_\-/]*)?$/;
const FORWARD_REQUEST = ["content-type", "cookie", "x-csrf-token", "origin", "sec-fetch-site", "accept", "user-agent"];
const MAX_BODY = 64 * 1024; // sama dengan batas backend (MAX_BODY_BYTES)

function error(status: number, code: string, message: string) {
  return Response.json({ error: { code, message } }, { status, headers: { "cache-control": "no-store" } });
}

async function readCapped(stream: ReadableStream<Uint8Array> | null, limit: number): Promise<ArrayBuffer | null> {
  if (!stream) return new ArrayBuffer(0);
  const reader = stream.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > limit) {
      await reader.cancel();
      return null;
    }
    chunks.push(value);
  }
  const out = new Uint8Array(size);
  let offset = 0;
  for (const c of chunks) {
    out.set(c, offset);
    offset += c.byteLength;
  }
  return out.buffer;
}

async function forward(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const backend = process.env.CLAU_BACKEND_URL;
  if (!backend) return error(503, "backend_unavailable", "Backend belum tersambung.");
  const path = (await params).path.join("/");
  if (!ALLOWED.test(path) || path.includes("..")) return error(404, "not_found", "Endpoint tidak ada.");

  const headers = new Headers();
  for (const name of FORWARD_REQUEST) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  let body: ArrayBuffer | undefined;
  if (!["GET", "HEAD"].includes(request.method)) {
    // Tolak dari header dulu, lalu baca bertahap dengan batas: body besar tidak pernah ditampung utuh di memori.
    if (Number(request.headers.get("content-length") ?? 0) > MAX_BODY) return error(413, "payload_too_large", "Body request terlalu besar.");
    const read = await readCapped(request.body, MAX_BODY);
    if (!read) return error(413, "payload_too_large", "Body request terlalu besar.");
    body = read;
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${backend.replace(/\/$/, "")}/${path}${request.nextUrl.search}`, {
      method: request.method,
      headers,
      body,
      redirect: "manual",
      cache: "no-store",
      signal: AbortSignal.timeout(15_000),
    });
  } catch {
    return error(502, "backend_unreachable", "Backend tidak bisa dihubungi.");
  }

  // Backend tidak pernah mengalihkan request API; redirect berarti salah alamat, jangan diteruskan ke browser.
  if (upstream.status >= 300 && upstream.status < 400) return error(502, "backend_unreachable", "Backend memberi respons tidak terduga.");

  const out = new Headers({ "cache-control": "no-store" });
  const type = upstream.headers.get("content-type");
  if (type) out.set("content-type", type);
  for (const cookie of upstream.headers.getSetCookie()) out.append("set-cookie", cookie);
  return new Response(upstream.status === 204 ? null : upstream.body, { status: upstream.status, headers: out });
}

export { forward as GET, forward as POST, forward as PUT, forward as PATCH, forward as DELETE };
