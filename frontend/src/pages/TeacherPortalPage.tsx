import { useCallback, useEffect, useState } from "react";
import { BookOpen, CalendarClock, Clock, GraduationCap, RefreshCw, ScanFace, Users } from "lucide-react";
import { api } from "../lib/api";
import type { AuthUser, Organization, TeacherAgendaResponse } from "../types/api";

interface TeacherPortalPageProps {
  currentUser: AuthUser;
  organization: Organization;
  onRefreshAll: () => Promise<void>;
  onOpenSessionInKiosk: (sessionId: number) => void;
}

const DAY_NAMES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"];

function getLocalDateAndTime(): { targetDate: string; currentTime: string } {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  const hh = String(now.getHours()).padStart(2, "0");
  const mm = String(now.getMinutes()).padStart(2, "0");
  return { targetDate: `${y}-${m}-${d}`, currentTime: `${hh}:${mm}` };
}

export function TeacherPortalPage({
  currentUser,
  organization,
  onRefreshAll,
  onOpenSessionInKiosk,
}: TeacherPortalPageProps) {
  const [agenda, setAgenda] = useState<TeacherAgendaResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [startingKey, setStartingKey] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const loadAgenda = useCallback(async () => {
    setLoading(true);
    setErrorMsg(null);
    try {
      const { targetDate, currentTime } = getLocalDateAndTime();
      const res = await api.getTeacherAgenda({
        organization_id: organization.id,
        target_date: targetDate,
        current_time: currentTime,
      });
      setAgenda(res);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "No se pudo cargar tu agenda docente.");
    } finally {
      setLoading(false);
    }
  }, [organization.id]);

  useEffect(() => {
    void loadAgenda();
  }, [loadAgenda]);

  async function handleStartAttendance(
    courseId: number,
    scheduleId?: number | null,
    key?: string
  ) {
    setStartingKey(key ?? `course-${courseId}`);
    setErrorMsg(null);
    try {
      const { targetDate } = getLocalDateAndTime();
      const sess = await api.startCourseSession(courseId, {
        schedule_id: scheduleId ?? null,
        session_date: agenda?.target_date ?? targetDate,
      });
      await onRefreshAll();
      onOpenSessionInKiosk(sess.id);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "No se pudo abrir la sesión de clase.");
    } finally {
      setStartingKey(null);
    }
  }

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <BookOpen className="w-6 h-6 text-indigo-400" />
            Mi Agenda Docente
          </h2>
          <p className="text-sm text-slate-400">
            Hola, <strong className="text-slate-200">{currentUser.full_name}</strong> · Acceso
            exclusivo a tus asignaturas y grupos asignados
          </p>
        </div>

        <button
          type="button"
          onClick={() => void loadAgenda()}
          className="inline-flex items-center gap-2 px-3.5 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-xs font-medium"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          Actualizar horario
        </button>
      </div>

      {errorMsg && (
        <div className="rounded-xl bg-red-500/15 border border-red-500/40 px-4 py-3 text-sm text-red-200">
          {errorMsg}
        </div>
      )}

      {loading ? (
        <div className="py-12 text-center text-sm text-slate-400">Cargando tu horario...</div>
      ) : !agenda ? null : (
        <>
          {/* Tu clase ahora */}
          {agenda.current_slot ? (
            <div className="rounded-3xl bg-gradient-to-br from-indigo-950/80 via-slate-900 to-slate-900 border border-indigo-500/40 p-6 flex flex-col md:flex-row md:items-center justify-between gap-5 shadow-lg">
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <span
                    className={`px-2.5 py-0.5 rounded-full text-xs font-semibold ${
                      agenda.current_slot.slot_status === "in_progress"
                        ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40"
                        : "bg-amber-500/20 text-amber-300 border border-amber-500/40"
                    }`}
                  >
                    {agenda.current_slot.slot_status === "in_progress"
                      ? "Tu clase ahora (En curso)"
                      : "Próxima clase de hoy"}
                  </span>
                  <span className="text-xs text-slate-400">
                    {agenda.current_slot.start_time} – {agenda.current_slot.end_time}
                    {agenda.current_slot.classroom ? ` · ${agenda.current_slot.classroom}` : ""}
                  </span>
                </div>

                <h3 className="text-2xl font-bold tracking-tight">
                  {agenda.current_slot.subject_name}{" "}
                  <span className="text-base font-normal text-indigo-300">
                    ({agenda.current_slot.subject_code})
                  </span>
                </h3>

                <p className="text-sm text-slate-300">
                  Grupo <strong>{agenda.current_slot.group_name}</strong>
                  {agenda.current_slot.career_name ? ` · ${agenda.current_slot.career_name}` : ""} ·{" "}
                  {agenda.current_slot.students_count} alumnos inscritos
                </p>
              </div>

              <button
                type="button"
                disabled={startingKey === `hero-${agenda.current_slot.schedule_id}`}
                onClick={() =>
                  void handleStartAttendance(
                    agenda.current_slot!.course_assignment_id,
                    agenda.current_slot!.schedule_id,
                    `hero-${agenda.current_slot!.schedule_id}`
                  )
                }
                className="inline-flex items-center justify-center gap-2 px-6 py-3.5 rounded-2xl bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white font-semibold text-sm shrink-0 shadow-md"
              >
                <ScanFace className="w-5 h-5" />
                {startingKey === `hero-${agenda.current_slot.schedule_id}`
                  ? "Abriendo kiosco..."
                  : "Tomar asistencia ahora"}
              </button>
            </div>
          ) : (
            <div className="rounded-2xl bg-slate-900 border border-slate-800 p-5 text-sm text-slate-400">
              No tienes clases programadas activas o próximas para lo que resta de hoy (
              <span className="text-slate-200">{agenda.target_date}</span>). Aún puedes abrir el
              pase de lista directamente desde tus materias asignadas abajo.
            </div>
          )}

          {/* Clases de hoy */}
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-3">
            <h3 className="font-semibold text-base flex items-center gap-2">
              <CalendarClock className="w-4 h-4 text-indigo-400" />
              Clases de hoy ({agenda.today_slots.length})
            </h3>

            {agenda.today_slots.length === 0 ? (
              <p className="text-xs text-slate-500 py-3">
                Hoy ({DAY_NAMES[(new Date(`${agenda.target_date}T12:00:00`).getDay() + 6) % 7]}) no
                tienes bloques en tu horario semanal.
              </p>
            ) : (
              <div className="space-y-2.5">
                {agenda.today_slots.map((slot) => {
                  const slotKey = `slot-${slot.schedule_id}`;
                  return (
                    <div
                      key={slot.schedule_id}
                      className="rounded-xl bg-slate-800/50 border border-slate-800 px-4 py-3 flex flex-wrap items-center justify-between gap-3"
                    >
                      <div className="space-y-0.5">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-xs font-mono text-indigo-300">
                            {slot.start_time}–{slot.end_time}
                          </span>
                          <span className="font-semibold text-sm">{slot.subject_name}</span>
                          <span className="text-xs text-slate-400">· {slot.group_name}</span>
                          <span
                            className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${
                              slot.slot_status === "in_progress"
                                ? "bg-emerald-500/20 text-emerald-300"
                                : slot.slot_status === "upcoming"
                                ? "bg-amber-500/20 text-amber-300"
                                : "bg-slate-700 text-slate-300"
                            }`}
                          >
                            {slot.slot_status === "in_progress"
                              ? "En curso"
                              : slot.slot_status === "upcoming"
                              ? "Próxima"
                              : "Finalizada"}
                          </span>
                        </div>
                        <p className="text-xs text-slate-400">
                          {slot.classroom ? `${slot.classroom} · ` : ""}
                          {slot.students_count} alumnos
                          {slot.session
                            ? ` · Sesión ${slot.session.status === "open" ? "abierta" : "cerrada"} (${slot.session.events_count} registros)`
                            : ""}
                        </p>
                      </div>

                      <button
                        type="button"
                        disabled={startingKey === slotKey}
                        onClick={() =>
                          void handleStartAttendance(
                            slot.course_assignment_id,
                            slot.schedule_id,
                            slotKey
                          )
                        }
                        className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-xs font-semibold text-white"
                      >
                        <ScanFace className="w-3.5 h-3.5" />
                        {startingKey === slotKey ? "Abriendo..." : "Tomar asistencia"}
                      </button>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Mis materias y grupos */}
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-3">
            <h3 className="font-semibold text-base flex items-center gap-2">
              <GraduationCap className="w-4 h-4 text-indigo-400" />
              Mis materias y grupos ({agenda.courses.length})
            </h3>

            {agenda.courses.length === 0 ? (
              <p className="text-xs text-slate-500 py-4 text-center">
                Aún no tienes materias asignadas. Solicita al administrador de la institución que te
                asigne tus cursos en <em>Estructura Académica</em>.
              </p>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {agenda.courses.map((course) => {
                  const key = `course-${course.id}`;
                  return (
                    <div
                      key={course.id}
                      className="rounded-xl bg-slate-800/40 border border-slate-800 p-4 space-y-3"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div>
                          <span className="px-2 py-0.5 rounded bg-indigo-500/20 text-indigo-300 text-[11px] font-semibold">
                            {course.subject_code}
                          </span>
                          <h4 className="font-bold text-base mt-1">{course.subject_name}</h4>
                          <p className="text-xs text-slate-400">
                            Grupo <strong className="text-slate-200">{course.group_name}</strong>
                            {course.career_name ? ` · ${course.career_name}` : ""}
                          </p>
                        </div>
                        <span className="inline-flex items-center gap-1 text-xs text-slate-300 bg-slate-800 px-2.5 py-1 rounded-lg">
                          <Users className="w-3.5 h-3.5 text-indigo-400" />
                          {course.students_count}
                        </span>
                      </div>

                      <div className="space-y-1">
                        {course.schedules.length === 0 ? (
                          <p className="text-[11px] text-slate-500">Sin bloques semanales definidos</p>
                        ) : (
                          course.schedules.map((sl) => (
                            <p
                              key={sl.id}
                              className="text-xs text-slate-300 flex items-center gap-1.5"
                            >
                              <Clock className="w-3 h-3 text-slate-400" />
                              {DAY_NAMES[sl.day_of_week] ?? `Día ${sl.day_of_week}`} {sl.start_time}
                              –{sl.end_time}
                              {sl.classroom ? ` · ${sl.classroom}` : ""}
                            </p>
                          ))
                        )}
                      </div>

                      <button
                        type="button"
                        disabled={startingKey === key}
                        onClick={() => void handleStartAttendance(course.id, null, key)}
                        className="w-full inline-flex items-center justify-center gap-1.5 py-2 rounded-xl bg-emerald-600/20 border border-emerald-500/40 hover:bg-emerald-600/30 text-emerald-300 text-xs font-semibold"
                      >
                        <ScanFace className="w-3.5 h-3.5" />
                        {startingKey === key ? "Iniciando..." : "Abrir pase de lista"}
                      </button>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
