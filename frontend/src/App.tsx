/**
 * Componente raíz de la aplicación web IdentIA.
 * Centraliza el estado global de autenticación JWT, la organización activa y
 * sus catálogos compartidos (grupos, personas, sesiones y eventos), además de
 * coordinar la navegación segura según rol y modo (`education` o `enterprise`).
 */
import { useCallback, useEffect, useState } from "react";
import { DisenoPrincipal, type PestanaNavegacion } from "./components/Layout";
import {
  clienteApi,
  guardarTokenAlmacenado,
  obtenerTokenAlmacenado,
  registrarManejadorNoAutorizado,
} from "./lib/api";
import { PaginaAcademico } from "./pages/AcademicPage";
import { PaginaPanelGeneral } from "./pages/DashboardPage";
import { PaginaEnrolamiento } from "./pages/EnrollmentPage";
import { PaginaTurnosEmpresariales } from "./pages/EnterpriseShiftsPage";
import { PaginaKiosco } from "./pages/KioskPage";
import { PaginaInicioSesion } from "./pages/LoginPage";
import { PaginaSeguridad } from "./pages/SecurityPage";
import { PaginaSesiones } from "./pages/SessionsPage";
import { PaginaPortalDocente } from "./pages/TeacherPortalPage";
import type {
  EventoAsistencia,
  Grupo,
  Organizacion,
  Persona,
  RespuestaInicioSesion,
  RespuestaSalud,
  SesionAsistencia,
  UsuarioAutenticado,
} from "./types/api";

/**
 * Componente principal exportado de IdentIA; gestiona el ciclo de vida de
 * la sesión y distribuye datos y callbacks hacia cada vista funcional.
 */
export function Aplicacion() {
  const [usuarioActual, establecerUsuarioActual] =
    useState<UsuarioAutenticado | null>(null);
  const [verificandoSesion, establecerVerificandoSesion] = useState(true);

  const [pestanaActiva, establecerPestanaActiva] =
    useState<PestanaNavegacion>("dashboard");
  const [idSesionObjetivoKiosco, establecerIdSesionObjetivoKiosco] = useState<
    number | null
  >(null);
  const [estadoSalud, establecerEstadoSalud] = useState<RespuestaSalud | null>(null);
  const [organizaciones, establecerOrganizaciones] = useState<Organizacion[]>([]);
  const [idOrganizacionSeleccionada, establecerIdOrganizacionSeleccionada] = useState<
    number | null
  >(null);

  const [grupos, establecerGrupos] = useState<Grupo[]>([]);
  const [personas, establecerPersonas] = useState<Persona[]>([]);
  const [sesiones, establecerSesiones] = useState<SesionAsistencia[]>([]);
  const [eventos, establecerEventos] = useState<EventoAsistencia[]>([]);
  const [cargando, establecerCargando] = useState(false);
  const [errorCarga, establecerErrorCarga] = useState<string | null>(null);

  /** Cierra la sesión local, limpia el JWT y restablece el estado en memoria. */
  const manejarCierreSesion = useCallback(() => {
    guardarTokenAlmacenado(null);
    establecerUsuarioActual(null);
    establecerOrganizaciones([]);
    establecerIdOrganizacionSeleccionada(null);
    establecerGrupos([]);
    establecerPersonas([]);
    establecerSesiones([]);
    establecerEventos([]);
    establecerIdSesionObjetivoKiosco(null);
    establecerPestanaActiva("dashboard");
  }, []);

  /** Navega al kiosco preseleccionando una sesión específica recién abierta. */
  const manejarAbrirSesionEnKiosco = useCallback((idSesion: number) => {
    establecerIdSesionObjetivoKiosco(idSesion);
    establecerPestanaActiva("kiosk");
  }, []);

  /** Carga en paralelo todos los datos operativos de la organización elegida. */
  const cargarDatosOrganizacion = useCallback(async (idOrganizacion: number) => {
    const [listaGrupos, listaPersonas, listaSesiones, listaEventos, salud] =
      await Promise.all([
        clienteApi.listarGrupos(idOrganizacion),
        clienteApi.listarPersonas(idOrganizacion),
        clienteApi.listarSesiones(idOrganizacion),
        clienteApi.listarEventos(idOrganizacion),
        clienteApi.obtenerSalud(),
      ]);
    establecerGrupos(listaGrupos);
    establecerPersonas(listaPersonas);
    establecerSesiones(listaSesiones);
    establecerEventos(listaEventos);
    establecerEstadoSalud(salud);
  }, []);

  /** Inicializa el catálogo de organizaciones y ajusta la vista según rol/modo. */
  const inicializarEspacioTrabajo = useCallback(
    async (
      idOrganizacionPreferido?: number,
      usuarioParaEnrutado?: UsuarioAutenticado | null
    ) => {
      establecerCargando(true);
      try {
        establecerErrorCarga(null);
        const [salud, listaOrganizaciones] = await Promise.all([
          clienteApi.obtenerSalud(),
          clienteApi.listarOrganizaciones(),
        ]);
        establecerEstadoSalud(salud);
        establecerOrganizaciones(listaOrganizaciones);

        const idObjetivo =
          idOrganizacionPreferido ?? listaOrganizaciones[0]?.id ?? null;
        establecerIdOrganizacionSeleccionada(idObjetivo);
        const organizacionObjetivo =
          listaOrganizaciones.find((org) => org.id === idObjetivo) ?? null;

        if (
          usuarioParaEnrutado?.rol === "teacher" &&
          organizacionObjetivo?.modo === "education"
        ) {
          establecerPestanaActiva("teacher_portal");
        } else if (organizacionObjetivo?.modo === "enterprise") {
          establecerPestanaActiva((previa) =>
            previa === "academic" || previa === "teacher_portal"
              ? "dashboard"
              : previa
          );
        } else if (organizacionObjetivo?.modo === "education") {
          establecerPestanaActiva((previa) =>
            previa === "enterprise_shifts" ? "dashboard" : previa
          );
        }

        if (idObjetivo !== null) {
          await cargarDatosOrganizacion(idObjetivo);
        }
      } catch (errorInicializacion) {
        establecerErrorCarga(
          errorInicializacion instanceof Error
            ? `No se pudo cargar la información de IdentIA: ${errorInicializacion.message}`
            : "Error al iniciar el espacio de trabajo."
        );
      } finally {
        establecerCargando(false);
      }
    },
    [cargarDatosOrganizacion]
  );

  // Registra el manejador global 401 para cerrar la sesión ante tokens expirados.
  useEffect(() => {
    registrarManejadorNoAutorizado(() => {
      manejarCierreSesion();
    });
    return () => registrarManejadorNoAutorizado(null);
  }, [manejarCierreSesion]);

  // Intenta restaurar una sesión previa validando `/api/auth/me` al arrancar.
  useEffect(() => {
    async function restaurarSesion() {
      const tokenGuardado = obtenerTokenAlmacenado();
      if (!tokenGuardado) {
        establecerVerificandoSesion(false);
        return;
      }
      try {
        const perfilUsuario = await clienteApi.obtenerPerfilActual();
        establecerUsuarioActual(perfilUsuario);
        await inicializarEspacioTrabajo(
          perfilUsuario.id_organizacion ?? undefined,
          perfilUsuario
        );
      } catch {
        guardarTokenAlmacenado(null);
        establecerUsuarioActual(null);
      } finally {
        establecerVerificandoSesion(false);
      }
    }
    void restaurarSesion();
  }, [inicializarEspacioTrabajo]);

  /** Procesa el inicio de sesión exitoso cargando la organización asignada. */
  const manejarExitoInicioSesion = async (datosInicio: RespuestaInicioSesion) => {
    establecerUsuarioActual(datosInicio.usuario);
    establecerPestanaActiva("dashboard");
    await inicializarEspacioTrabajo(
      datosInicio.usuario.id_organizacion ?? undefined,
      datosInicio.usuario
    );
  };

  /** Cambia la organización activa desde el selector del superadministrador. */
  const manejarSeleccionOrganizacion = async (idOrganizacion: number) => {
    establecerIdOrganizacionSeleccionada(idOrganizacion);
    establecerIdSesionObjetivoKiosco(null);
    const organizacionObjetivo =
      organizaciones.find((org) => org.id === idOrganizacion) ?? null;

    if (organizacionObjetivo?.modo === "enterprise") {
      establecerPestanaActiva((previa) =>
        previa === "academic" || previa === "teacher_portal"
          ? "dashboard"
          : previa
      );
    } else if (
      usuarioActual?.rol === "teacher" &&
      organizacionObjetivo?.modo === "education"
    ) {
      establecerPestanaActiva("teacher_portal");
    } else if (organizacionObjetivo?.modo === "education") {
      establecerPestanaActiva((previa) =>
        previa === "enterprise_shifts" ? "dashboard" : previa
      );
    }

    await cargarDatosOrganizacion(idOrganizacion);
  };

  /** Recarga la organización actual y todos sus catálogos relacionados. */
  const recargarOrganizacionActual = useCallback(async () => {
    if (idOrganizacionSeleccionada === null) return;
    const listaOrganizaciones = await clienteApi.listarOrganizaciones();
    establecerOrganizaciones(listaOrganizaciones);
    await cargarDatosOrganizacion(idOrganizacionSeleccionada);
  }, [cargarDatosOrganizacion, idOrganizacionSeleccionada]);

  if (verificandoSesion) {
    return (
      <div className="min-h-screen bg-slate-950 text-slate-400 flex items-center justify-center text-sm">
        Verificando sesión...
      </div>
    );
  }

  if (!usuarioActual) {
    return (
      <PaginaInicioSesion
        alIniciarSesion={(respuesta) => void manejarExitoInicioSesion(respuesta)}
      />
    );
  }

  const organizacionSeleccionada =
    organizaciones.find((org) => org.id === idOrganizacionSeleccionada) ?? null;

  return (
    <DisenoPrincipal
      pestanaActiva={pestanaActiva}
      alCambiarPestana={establecerPestanaActiva}
      usuarioActual={usuarioActual}
      alCerrarSesion={manejarCierreSesion}
      organizaciones={organizaciones}
      organizacionSeleccionada={organizacionSeleccionada}
      alSeleccionarOrganizacion={(idOrg) => void manejarSeleccionOrganizacion(idOrg)}
      estadoSalud={estadoSalud}
    >
      {cargando ? (
        <div className="flex items-center justify-center h-64 text-sm text-slate-400">
          Cargando IdentIA...
        </div>
      ) : errorCarga ? (
        <div className="max-w-xl mx-auto mt-10 rounded-2xl bg-red-500/10 border border-red-500/40 p-6 text-sm text-red-200 space-y-3">
          <p className="font-semibold">Error de conexión</p>
          <p>{errorCarga}</p>
          <button
            type="button"
            onClick={() =>
              void inicializarEspacioTrabajo(idOrganizacionSeleccionada ?? undefined)
            }
            className="px-4 py-2 rounded-lg bg-red-600 hover:bg-red-500 text-white text-xs font-semibold"
          >
            Reintentar
          </button>
        </div>
      ) : !organizacionSeleccionada ? (
        <div className="text-center text-slate-400 py-16 text-sm">
          No hay organizaciones asignadas a tu usuario.
        </div>
      ) : (
        <>
          {pestanaActiva === "teacher_portal" &&
            organizacionSeleccionada.modo === "education" && (
              <PaginaPortalDocente
                usuarioActual={usuarioActual}
                organizacion={organizacionSeleccionada}
                alRecargarTodo={recargarOrganizacionActual}
                alAbrirSesionEnKiosco={manejarAbrirSesionEnKiosco}
              />
            )}

          {pestanaActiva === "dashboard" && usuarioActual.rol !== "teacher" && (
            <PaginaPanelGeneral
              usuarioActual={usuarioActual}
              organizacion={organizacionSeleccionada}
              estadoSalud={estadoSalud}
              personas={personas}
              eventos={eventos}
              alRecargarTodo={recargarOrganizacionActual}
              alCrearOrganizacion={async (idNuevaOrg) => {
                await inicializarEspacioTrabajo(idNuevaOrg);
              }}
              alNavegarPestana={establecerPestanaActiva}
            />
          )}

          {pestanaActiva === "kiosk" && (
            <PaginaKiosco
              usuarioActual={usuarioActual}
              organizacion={organizacionSeleccionada}
              grupos={grupos}
              sesiones={sesiones}
              eventos={eventos}
              idSesionInicial={idSesionObjetivoKiosco}
              alRecargarEventos={async () => {
                const listaEventos = await clienteApi.listarEventos(
                  organizacionSeleccionada.id
                );
                establecerEventos(listaEventos);
              }}
            />
          )}

          {pestanaActiva === "enrollment" && usuarioActual.rol !== "teacher" && (
            <PaginaEnrolamiento
              usuarioActual={usuarioActual}
              organizacion={organizacionSeleccionada}
              grupos={grupos}
              personas={personas}
              alRecargarPersonas={async () => {
                const [listaPersonas, salud] = await Promise.all([
                  clienteApi.listarPersonas(organizacionSeleccionada.id),
                  clienteApi.obtenerSalud(),
                ]);
                establecerPersonas(listaPersonas);
                establecerEstadoSalud(salud);
              }}
            />
          )}

          {pestanaActiva === "academic" &&
            organizacionSeleccionada.modo === "education" &&
            (usuarioActual.rol === "superadmin" ||
              usuarioActual.rol === "org_admin") && (
              <PaginaAcademico
                usuarioActual={usuarioActual}
                organizacion={organizacionSeleccionada}
                grupos={grupos}
                alRecargarOrganizacion={recargarOrganizacionActual}
                alAbrirSesionEnKiosco={manejarAbrirSesionEnKiosco}
              />
            )}

          {pestanaActiva === "enterprise_shifts" &&
            organizacionSeleccionada.modo === "enterprise" &&
            ["superadmin", "org_admin", "supervisor"].includes(
              usuarioActual.rol
            ) && (
              <PaginaTurnosEmpresariales
                usuarioActual={usuarioActual}
                organizacion={organizacionSeleccionada}
                grupos={grupos}
                personas={personas}
                alRecargarOrganizacion={recargarOrganizacionActual}
                alAbrirSesionEnKiosco={manejarAbrirSesionEnKiosco}
              />
            )}

          {pestanaActiva === "sessions" && (
            <PaginaSesiones
              usuarioActual={usuarioActual}
              organizacion={organizacionSeleccionada}
              grupos={grupos}
              sesiones={sesiones}
              personas={personas}
              eventos={eventos}
              alRecargarTodo={recargarOrganizacionActual}
            />
          )}

          {pestanaActiva === "security" &&
            (usuarioActual.rol === "superadmin" ||
              usuarioActual.rol === "org_admin") && (
              <PaginaSeguridad
                usuarioActual={usuarioActual}
                organizacion={organizacionSeleccionada}
              />
            )}
        </>
      )}
    </DisenoPrincipal>
  );
}

export default Aplicacion;
