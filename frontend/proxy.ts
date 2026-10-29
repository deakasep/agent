// Penjaga halaman (Next.js 16 "proxy", dulu middleware). Hanya aktif bila CLAU_AUTH_ENABLED=1 (docker compose /
// VPS 2). VPS 1 (pratinjau data SIMULASI tanpa backend) tidak mengaturnya, jadi tetap bisa dibuka seperti sekarang.
// Ini hanya pengalihan kenyamanan: keamanan sesungguhnya ada di backend (setiap endpoint mengecek sesi & peran).
import { NextResponse, type NextRequest } from "next/server";

// Nama cookie sesi: __Host- (produksi) atau tanpa Secure bila backend CLAU_ENV=development (Safari di localhost).
const SESSION_COOKIES = ["__Host-clau_session", "clau_session_dev"];

function isPublic(pathname: string) {
  // Halaman akun publik: daftar mandiri, verifikasi email, lupa & reset password.
  return ["/login", "/daftar", "/verifikasi-email", "/lupa-password", "/reset-password"].includes(pathname) || pathname.startsWith("/api/") || pathname.startsWith("/_next/") || /\.(webp|png|svg|ico|txt)$/.test(pathname);
}

export function proxy(request: NextRequest) {
  if (process.env.CLAU_AUTH_ENABLED !== "1") return NextResponse.next();
  const { pathname, search } = request.nextUrl;
  if (isPublic(pathname) || SESSION_COOKIES.some((c) => request.cookies.has(c))) return NextResponse.next();
  // Di balik reverse proxy HTTPS (Nginx, `tailscale serve`) server Next.js sendiri hanya melihat
  // http://127.0.0.1:3000; CLAU_PUBLIC_ORIGIN (alamat yang dibuka browser) membuat redirect tetap benar.
  const url = new URL("/login", process.env.CLAU_PUBLIC_ORIGIN || request.nextUrl.origin);
  url.search = `?next=${encodeURIComponent(pathname + search)}`;
  return NextResponse.redirect(url);
}

export const config = { matcher: ["/((?!_next/static|_next/image).*)"] };
