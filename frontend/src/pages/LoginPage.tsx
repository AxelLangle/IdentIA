/**
 * Pantalla de autenticación de IdentIA.
 * Permite acceder con credenciales JWT organizacionales e incluye accesos
 * rápidos para rellenar cuentas de demostración en entornos locales.
 */
import { useState, type FormEvent } from "react";
import { Lock, ScanFace } from "lucide-react";
import { EntradaContrasena } from "../components/PasswordInput";
import { clienteApi } from "../lib/api";
import type { RespuestaInicioSesion } from "../types/api";

/** Propiedades recibidas por el componente `PaginaInicioSesion`. */
interface PropiedadesPaginaInicioSesion {
  /** Callback ejecutado cuando el servidor emite un token JWT válido. */
  alIniciarSesion: (datosSesion: RespuestaInicioSesion) => void;
}

/**
 * Renderiza el formulario de acceso de IdentIA preservando selectores de prueba
 * (`#login-email` y `#login-password`) y manejo claro de errores.
 */
export function PaginaInicioSesion({
  alIniciarSesion,
}: PropiedadesPaginaInicioSesion) {
  const [correo, establecerCorreo] = useState("");
  const [contrasena, establecerContrasena] = useState("");
  const [cargando, establecerCargando] = useState(false);
  const [mensajeError, establecerMensajeError] = useState<string | null>(null);

  /** Envía el correo y contraseña capturados contra `POST /api/auth/login`. */
  async function manejarEnvio(evento: FormEvent) {
    evento.preventDefault();
    establecerCargando(true);
    establecerMensajeError(null);
    try {
      const respuesta = await clienteApi.iniciarSesion(correo.trim(), contrasena);
      alIniciarSesion(respuesta);
    } catch (errorInicio) {
      establecerMensajeError(
        errorInicio instanceof Error ? errorInicio.message : "No se pudo iniciar sesión."
      );
    } finally {
      establecerCargando(false);
    }
  }

  /** Completa los campos de entrada con una cuenta demo sin enviar el formulario. */
  function rellenarDemo(correoDemo: string, contrasenaDemo: string) {
    establecerCorreo(correoDemo);
    establecerContrasena(contrasenaDemo);
    establecerMensajeError(null);
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

        <form onSubmit={manejarEnvio} className="space-y-4">
          <div>
            <label htmlFor="login-email" className="block text-xs text-slate-400 mb-1.5">
              Correo electrónico
            </label>
            <input
              id="login-email"
              type="email"
              required
              autoComplete="email"
              value={correo}
              onChange={(evento) => establecerCorreo(evento.target.value)}
              placeholder="usuario@organizacion.com"
              className="w-full bg-slate-800 border border-slate-700 rounded-xl px-3.5 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          <div>
            <label
              htmlFor="login-password"
              className="block text-xs text-slate-400 mb-1.5"
            >
              Contraseña
            </label>
            <EntradaContrasena
              id="login-password"
              required
              autoComplete="current-password"
              value={contrasena}
              onChange={(evento) => establecerContrasena(evento.target.value)}
              placeholder="••••••••"
              className="w-full bg-slate-800 border border-slate-700 rounded-xl px-3.5 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          {mensajeError && (
            <p className="text-xs text-red-300 bg-red-500/10 border border-red-500/30 rounded-xl px-3 py-2">
              {mensajeError}
            </p>
          )}

          <button
            type="submit"
            disabled={cargando}
            className="w-full inline-flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-semibold bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white transition-colors"
          >
            <Lock className="w-4 h-4" />
            {cargando ? "Verificando..." : "Iniciar sesión"}
          </button>
        </form>

        <div className="rounded-2xl bg-slate-800/50 border border-slate-800 p-3.5 space-y-2 text-xs">
          <p className="font-semibold text-slate-300">Cuentas demo locales</p>
          <div className="flex flex-col gap-1.5 text-slate-400">
            <button
              type="button"
              onClick={() => rellenarDemo("admin@identia.local", "IdentIA2026!")}
              className="text-left hover:text-indigo-300 transition-colors"
            >
              • <strong>Superadmin:</strong> admin@identia.local / IdentIA2026!
            </button>
            <button
              type="button"
              onClick={() => rellenarDemo("empresa@identia.local", "Empresa2026!")}
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
