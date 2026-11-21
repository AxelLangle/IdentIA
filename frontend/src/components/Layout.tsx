/**
 * Marco principal de navegación de IdentIA.
 * Renderiza la barra lateral con el menú filtrado por rol y modo operativo,
 * el encabezado superior con selector de organización multi-tenant para
 * superadministradores, la ficha de sesión del usuario y el área principal.
 */
import type { ReactNode } from "react";
import {
  Activity,
  BookOpen,
  Briefcase,
  Building2,
  CalendarClock,
  GraduationCap,
  LayoutDashboard,
  LogOut,
  ScanFace,
  ShieldCheck,
  Users,
} from "lucide-react";
import type {
  Organizacion,
  RespuestaSalud,
  RolUsuario,
  UsuarioAutenticado,
} from "../types/api";

/** Identificadores válidos de las pestañas de navegación en la aplicación. */
export type PestanaNavegacion =
  | "dashboard"
  | "kiosk"
  | "enrollment"
  | "sessions"
  | "academic"
  | "enterprise_shifts"
  | "teacher_portal"
  | "security";

/** Propiedades recibidas por el contenedor principal `DisenoPrincipal`. */
interface PropiedadesDisenoPrincipal {
  /** Pestaña activa actualmente en el espacio de trabajo. */
  pestanaActiva: PestanaNavegacion;
  /** Callback ejecutado cuando el usuario cambia de vista en la barra lateral. */
  alCambiarPestana: (pestana: PestanaNavegacion) => void;
  /** Perfil del usuario autenticado mediante JWT. */
  usuarioActual: UsuarioAutenticado;
  /** Callback para cerrar la sesión actual. */
  alCerrarSesion: () => void;
  /** Lista de organizaciones accesibles para el usuario. */
  organizaciones: Organizacion[];
  /** Organización seleccionada actualmente como contexto activo. */
  organizacionSeleccionada: Organizacion | null;
  /** Callback ejecutado cuando el superadmin elige otra organización. */
  alSeleccionarOrganizacion: (idOrganizacion: number) => void;
  /** Diagnóstico más reciente de disponibilidad de modelos ONNX. */
  estadoSalud: RespuestaSalud | null;
  /** Vista hija correspondiente a la pestaña activa. */
  children: ReactNode;
}

/** Etiquetas legibles mostradas en la ficha superior según el rol del usuario. */
const ETIQUETAS_ROL: Record<RolUsuario, string> = {
  superadmin: "Superadmin",
  org_admin: "Admin Org",
  teacher: "Profesor",
  supervisor: "Supervisor",
  operator: "Operador",
};

/**
 * Envuelve el contenido autenticado dentro de la barra lateral de navegación,
 * barra superior de contexto organizacional y contenedor de página principal.
 */
export function DisenoPrincipal({
  pestanaActiva,
  alCambiarPestana,
  usuarioActual,
  alCerrarSesion,
  organizaciones,
  organizacionSeleccionada,
  alSeleccionarOrganizacion,
  estadoSalud,
  children,
}: PropiedadesDisenoPrincipal) {
  const puedeVerSeguridad =
    usuarioActual.rol === "superadmin" || usuarioActual.rol === "org_admin";
  const esEducacion = organizacionSeleccionada?.modo === "education";
  const esEmpresa = organizacionSeleccionada?.modo === "enterprise";
  const esDocente = usuarioActual.rol === "teacher";

  // Catálogo declarativo de navegación sujeto a permisos por rol y modo.
  const elementosNavegacion: {
    id: PestanaNavegacion;
    etiqueta: string;
    icono: typeof LayoutDashboard;
    visible: boolean;
  }[] = [
    {
      id: "teacher_portal",
      etiqueta: "Mi Agenda Docente",
      icono: BookOpen,
      visible: esEducacion && esDocente,
    },
    { id: "dashboard", etiqueta: "Dashboard", icono: LayoutDashboard, visible: !esDocente },
    { id: "kiosk", etiqueta: "Kiosco en vivo", icono: ScanFace, visible: true },
    { id: "enrollment", etiqueta: "Personas y Registro", icono: Users, visible: !esDocente },
    {
      id: "academic",
      etiqueta: "Estructura Académica",
      icono: GraduationCap,
      visible: esEducacion && puedeVerSeguridad,
    },
    {
      id: "enterprise_shifts",
      etiqueta: "Turnos y Jornadas",
      icono: Briefcase,
      visible: esEmpresa && (puedeVerSeguridad || usuarioActual.rol === "supervisor"),
    },
    {
      id: "sessions",
      etiqueta: esDocente ? "Mis Sesiones" : "Grupos y Sesiones",
      icono: CalendarClock,
      visible: true,
    },
    {
      id: "security",
      etiqueta: "Seguridad y Usuarios",
      icono: ShieldCheck,
      visible: puedeVerSeguridad,
    },
  ];

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col md:flex-row">
      {/* Barra lateral */}
      <aside className="w-full md:w-64 bg-slate-900 border-b md:border-b-0 md:border-r border-slate-800 flex flex-col justify-between shrink-0">
        <div>
          <div className="px-5 py-5 border-b border-slate-800 flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-indigo-600/20 border border-indigo-500/40 flex items-center justify-center text-indigo-400">
              <ScanFace className="w-5 h-5" />
            </div>
            <div>
              <h1 className="font-bold tracking-tight text-lg leading-none">IdentIA</h1>
              <p className="text-xs text-slate-400 mt-1">Asistencia Biométrica</p>
            </div>
          </div>

          <nav className="p-3 flex md:flex-col gap-1 overflow-x-auto">
            {elementosNavegacion
              .filter((elemento) => elemento.visible)
              .map((elemento) => {
                const Icono = elemento.icono;
                const estaActiva = pestanaActiva === elemento.id;
                return (
                  <button
                    key={elemento.id}
                    type="button"
                    onClick={() => alCambiarPestana(elemento.id)}
                    className={`flex items-center gap-3 px-3.5 py-2.5 rounded-lg text-sm font-medium transition-colors whitespace-nowrap ${
                      estaActiva
                        ? "bg-indigo-600 text-white shadow-sm"
                        : "text-slate-300 hover:bg-slate-800/80 hover:text-white"
                    }`}
                  >
                    <Icono className="w-4 h-4 shrink-0" />
                    <span>{elemento.etiqueta}</span>
                  </button>
                );
              })}
          </nav>
        </div>

        <div className="hidden md:block p-4 border-t border-slate-800 text-xs text-slate-400 space-y-2.5">
          <div className="flex items-center justify-between">
            <span className="flex items-center gap-1.5">
              <Activity className="w-3.5 h-3.5 text-emerald-400" />
              Motor IA
            </span>
            <span
              className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${
                estadoSalud?.modelos_cargados
                  ? "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30"
                  : "bg-amber-500/15 text-amber-300 border border-amber-500/30"
              }`}
            >
              {estadoSalud?.modelos_cargados ? "YuNet + SFace" : "Cargando"}
            </span>
          </div>
          <p className="text-[11px] text-slate-500">
            Privacidad activa: embeddings L2 en memoria, sin fotos crudas en disco.
          </p>
        </div>
      </aside>

      {/* Contenido principal */}
      <div className="flex-1 flex flex-col min-w-0">
        <header className="min-h-16 py-2 border-b border-slate-800 bg-slate-900/60 backdrop-blur px-4 sm:px-6 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3 min-w-0">
            <span className="text-xs uppercase tracking-wider text-slate-400 hidden sm:inline">
              Organización
            </span>

            {usuarioActual.rol === "superadmin" ? (
              <select
                id="org-selector"
                value={organizacionSeleccionada?.id ?? ""}
                onChange={(evento) => alSeleccionarOrganizacion(Number(evento.target.value))}
                className="bg-slate-800 border border-slate-700 text-slate-100 text-sm rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-indigo-500 max-w-xs truncate"
              >
                {organizaciones.map((organizacion) => (
                  <option key={organizacion.id} value={organizacion.id}>
                    {organizacion.nombre}
                  </option>
                ))}
              </select>
            ) : (
              <span className="text-sm font-semibold text-slate-100 truncate max-w-xs">
                {organizacionSeleccionada?.nombre ?? "Sin organización"}
              </span>
            )}

            {organizacionSeleccionada && (
              <span
                className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border ${
                  organizacionSeleccionada.modo === "enterprise"
                    ? "bg-indigo-500/15 text-indigo-300 border-indigo-500/30"
                    : "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"
                }`}
              >
                {organizacionSeleccionada.modo === "enterprise" ? (
                  <>
                    <Building2 className="w-3.5 h-3.5" />
                    Empresa (Check-in/out)
                  </>
                ) : (
                  <>
                    <GraduationCap className="w-3.5 h-3.5" />
                    Escuela (Pase de lista)
                  </>
                )}
              </span>
            )}
          </div>

          <div className="flex items-center gap-3">
            <div className="text-right hidden sm:block">
              <p className="text-xs font-semibold text-slate-200 leading-tight">
                {usuarioActual.nombre_completo}
              </p>
              <p className="text-[11px] text-indigo-300">
                {ETIQUETAS_ROL[usuarioActual.rol]} · {usuarioActual.correo}
              </p>
            </div>
            <button
              type="button"
              onClick={alCerrarSesion}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200"
              title="Cerrar sesión"
            >
              <LogOut className="w-3.5 h-3.5" />
              Salir
            </button>
          </div>
        </header>

        <main className="flex-1 p-4 sm:p-6 overflow-y-auto">{children}</main>
      </div>
    </div>
  );
}
