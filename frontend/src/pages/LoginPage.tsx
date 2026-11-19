import { useState, type FormEvent } from "react";
import { Lock, ScanFace } from "lucide-react";
import { api } from "../lib/api";
import type { LoginResponse } from "../types/api";

interface LoginPageProps {
  onSuccess: (loginData: LoginResponse) => void;
}

export function LoginPage({ onSuccess }: LoginPageProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setLoading(true);
    setErrorMsg(null);
    try {
      const res = await api.login(email.trim(), password);
      onSuccess(res);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "No se pudo iniciar sesión.");
    } finally {
      setLoading(false);
    }
  }

  function fillDemo(demoEmail: string, demoPassword: string) {
    setEmail(demoEmail);
    setPassword(demoPassword);
    setErrorMsg(null);
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex items-center justify-center p-4">
      <div className="w-full max-w-md bg-slate-900 border border-slate-800 rounded-3xl p-7 shadow-2xl space-y-6">
        <div className="flex items-center gap-3">
          <div className="w-11 h-11 rounded-2xl bg-indigo-600/20 border border-indigo-500/40 flex items-center justify-center text-indigo-400">
            <ScanFace className="w-6 h-6" />
          </div>
          <div>
            <h1 className="text-xl font-bold tracking-tight">IdentIA</h1>
            <p className="text-xs text-slate-400">Acceso seguro multi-organización</p>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="login-email" className="block text-xs text-slate-400 mb-1.5">
              Correo electrónico
            </label>
            <input
              id="login-email"
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="usuario@organizacion.com"
              className="w-full bg-slate-800 border border-slate-700 rounded-xl px-3.5 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          <div>
            <label htmlFor="login-password" className="block text-xs text-slate-400 mb-1.5">
              Contraseña
            </label>
            <input
              id="login-password"
              type="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              className="w-full bg-slate-800 border border-slate-700 rounded-xl px-3.5 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          {errorMsg && (
            <p className="text-xs text-red-300 bg-red-500/10 border border-red-500/30 rounded-xl px-3 py-2">
              {errorMsg}
            </p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full inline-flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-semibold bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white transition-colors"
          >
            <Lock className="w-4 h-4" />
            {loading ? "Verificando..." : "Iniciar sesión"}
          </button>
        </form>

        <div className="rounded-2xl bg-slate-800/50 border border-slate-800 p-3.5 space-y-2 text-xs">
          <p className="font-semibold text-slate-300">Cuentas demo locales</p>
          <div className="flex flex-col gap-1.5 text-slate-400">
            <button
              type="button"
              onClick={() => fillDemo("admin@identia.local", "IdentIA2026!")}
              className="text-left hover:text-indigo-300 transition-colors"
            >
              • <strong>Superadmin:</strong> admin@identia.local / IdentIA2026!
            </button>
            <button
              type="button"
              onClick={() => fillDemo("empresa@identia.local", "Empresa2026!")}
              className="text-left hover:text-indigo-300 transition-colors"
            >
              • <strong>Admin Organización:</strong> empresa@identia.local / Empresa2026!
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
