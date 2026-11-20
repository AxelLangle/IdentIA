import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  BarChart3,
  BookOpen,
  CalendarCheck,
  ChevronDown,
  ChevronUp,
  Clock,
  GraduationCap,
  Layers,
  Plus,
  ScanFace,
  Trash2,
} from "lucide-react";
import { api } from "../lib/api";
import type {
  AcademicStatsResponse,
  AuthUser,
  Career,
  CourseAssignment,
  Group,
  Organization,
  Subject,
} from "../types/api";

interface AcademicPageProps {
  currentUser: AuthUser;
  organization: Organization;
  groups: Group[];
  onRefreshOrg: () => Promise<void>;
  onOpenSessionInKiosk: (sessionId: number) => void;
}

type AcademicSubTab = "structure" | "courses" | "stats";

const WEEKDAYS = [
  { value: 0, label: "Lunes" },
  { value: 1, label: "Martes" },
  { value: 2, label: "Miércoles" },
  { value: 3, label: "Jueves" },
  { value: 4, label: "Viernes" },
  { value: 5, label: "Sábado" },
  { value: 6, label: "Domingo" },
];

function dayLabel(day: number): string {
  return WEEKDAYS.find((d) => d.value === day)?.label ?? `Día ${day}`;
}

function getTodayIso(): string {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

export function AcademicPage({
  organization,
  groups,
  onRefreshOrg,
  onOpenSessionInKiosk,
}: AcademicPageProps) {
  const [subTab, setSubTab] = useState<AcademicSubTab>("structure");
  const [careers, setCareers] = useState<Career[]>([]);
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [courses, setCourses] = useState<CourseAssignment[]>([]);
  const [teachers, setTeachers] = useState<AuthUser[]>([]);
  const [stats, setStats] = useState<AcademicStatsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Alta de carrera
  const [careerName, setCareerName] = useState("");
  const [careerCode, setCareerCode] = useState("");
  const [careerDesc, setCareerDesc] = useState("");

  // Alta de grupo académico
  const [groupName, setGroupName] = useState("");
  const [groupCode, setGroupCode] = useState("");
  const [groupCareerId, setGroupCareerId] = useState<string>("");
  const [groupSemester, setGroupSemester] = useState("");

  // Alta de asignatura
  const [subjectName, setSubjectName] = useState("");
  const [subjectCode, setSubjectCode] = useState("");
  const [subjectCareerId, setSubjectCareerId] = useState<string>("");

  // Alta de curso (Grupo + Materia + Profesor + horario inicial)
  const [courseGroupId, setCourseGroupId] = useState<string>("");
  const [courseSubjectId, setCourseSubjectId] = useState<string>("");
  const [courseTeacherId, setCourseTeacherId] = useState<string>("");
  const [courseTerm, setCourseTerm] = useState("");
  const [initDay, setInitDay] = useState<number>(new Date().getDay() === 0 ? 6 : new Date().getDay() - 1);
  const [initStart, setInitStart] = useState("10:00");
  const [initEnd, setInitEnd] = useState("11:00");
  const [initClassroom, setInitClassroom] = useState("");

  // Nuevo bloque horario inline por curso
  const [scheduleDrafts, setScheduleDrafts] = useState<
    Record<number, { day: number; start: string; end: string; classroom: string }>
  >({});

  // Filtros de estadísticas
  const [statsDateFrom, setStatsDateFrom] = useState("");
  const [statsDateTo, setStatsDateTo] = useState("");
  const [statsCareerId, setStatsCareerId] = useState<string>("");
  const [statsGroupId, setStatsGroupId] = useState<string>("");
  const [expandedGroupIds, setExpandedGroupIds] = useState<Record<number, boolean>>({});

  const loadAcademicData = useCallback(async () => {
    setLoading(true);
    setErrorMsg(null);
    try {
      const [carList, subjList, courseList, usersList] = await Promise.all([
        api.listCareers(organization.id),
        api.listSubjects(organization.id),
        api.listCourses(organization.id),
        api.listUsers(organization.id),
      ]);
      setCareers(carList);
      setSubjects(subjList);
      setCourses(courseList);
      setTeachers(usersList.filter((u) => u.is_active && (u.role === "teacher" || u.role === "org_admin")));
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "No se pudo cargar la estructura académica.");
    } finally {
      setLoading(false);
    }
  }, [organization.id]);

  const loadStats = useCallback(async () => {
    try {
      const res = await api.getAcademicStats({
        organization_id: organization.id,
        date_from: statsDateFrom || null,
        date_to: statsDateTo || null,
        career_id: statsCareerId ? Number(statsCareerId) : null,
        group_id: statsGroupId ? Number(statsGroupId) : null,
      });
      setStats(res);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Error cargando estadísticas.");
    }
  }, [organization.id, statsCareerId, statsDateFrom, statsDateTo, statsGroupId]);

  useEffect(() => {
    void loadAcademicData();
  }, [loadAcademicData]);

  useEffect(() => {
    if (subTab === "stats") {
      void loadStats();
    }
  }, [subTab, loadStats]);

  async function handleCreateCareer(e: FormEvent) {
    e.preventDefault();
    setErrorMsg(null);
    setStatusMsg(null);
    try {
      await api.createCareer({
        organization_id: organization.id,
        name: careerName.trim(),
        code: careerCode.trim(),
        description: careerDesc.trim() || null,
      });
      setCareerName("");
      setCareerCode("");
      setCareerDesc("");
      setStatusMsg("Carrera registrada.");
      await loadAcademicData();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Error creando carrera.");
    }
  }

  async function handleDeleteCareer(careerId: number) {
    setErrorMsg(null);
    try {
      await api.deleteCareer(careerId);
      await Promise.all([loadAcademicData(), onRefreshOrg()]);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "No se pudo eliminar la carrera.");
    }
  }

  async function handleCreateGroup(e: FormEvent) {
    e.preventDefault();
    setErrorMsg(null);
    setStatusMsg(null);
    try {
      await api.createGroup({
        organization_id: organization.id,
        name: groupName.trim(),
        code: groupCode.trim(),
        career_id: groupCareerId ? Number(groupCareerId) : null,
        semester: groupSemester.trim() || null,
        schedule_start: "07:00",
        schedule_end: "15:00",
      });
      setGroupName("");
      setGroupCode("");
      setGroupSemester("");
      setStatusMsg("Grupo académico creado.");
      await Promise.all([onRefreshOrg(), loadAcademicData()]);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Error creando grupo.");
    }
  }

  async function handleLinkGroupCareer(groupId: number, careerIdStr: string) {
    setErrorMsg(null);
    try {
      await api.updateGroup(groupId, {
        career_id: careerIdStr ? Number(careerIdStr) : null,
      });
      await Promise.all([onRefreshOrg(), loadAcademicData()]);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "No se pudo actualizar la carrera del grupo.");
    }
  }

  async function handleDeleteGroup(groupId: number) {
    setErrorMsg(null);
    try {
      await api.deleteGroup(groupId);
      await Promise.all([onRefreshOrg(), loadAcademicData()]);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Error eliminando grupo.");
    }
  }

  async function handleCreateSubject(e: FormEvent) {
    e.preventDefault();
    setErrorMsg(null);
    setStatusMsg(null);
    try {
      await api.createSubject({
        organization_id: organization.id,
        career_id: subjectCareerId ? Number(subjectCareerId) : null,
        name: subjectName.trim(),
        code: subjectCode.trim(),
      });
      setSubjectName("");
      setSubjectCode("");
      setStatusMsg("Asignatura agregada al catálogo.");
      await loadAcademicData();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Error creando asignatura.");
    }
  }

  async function handleDeleteSubject(subjectId: number) {
    setErrorMsg(null);
    try {
      await api.deleteSubject(subjectId);
      await loadAcademicData();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Error eliminando asignatura.");
    }
  }

  async function handleCreateCourse(e: FormEvent) {
    e.preventDefault();
    if (!courseGroupId || !courseSubjectId) return;
    setErrorMsg(null);
    setStatusMsg(null);
    try {
      await api.createCourse({
        organization_id: organization.id,
        group_id: Number(courseGroupId),
        subject_id: Number(courseSubjectId),
        teacher_user_id: courseTeacherId ? Number(courseTeacherId) : null,
        term: courseTerm.trim() || null,
        schedules: [
          {
            day_of_week: initDay,
            start_time: initStart,
            end_time: initEnd,
            classroom: initClassroom.trim() || null,
          },
        ],
      });
      setInitClassroom("");
      setStatusMsg("Asignatura vinculada al grupo con su horario. Los alumnos del grupo la heredan automáticamente.");
      await Promise.all([loadAcademicData(), onRefreshOrg()]);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Error asignando asignatura.");
    }
  }

  async function handleReassignTeacher(courseId: number, teacherIdStr: string) {
    setErrorMsg(null);
    try {
      await api.updateCourse(courseId, {
        teacher_user_id: teacherIdStr ? Number(teacherIdStr) : null,
      });
      await loadAcademicData();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "No se pudo cambiar el profesor.");
    }
  }

  async function handleAddSchedule(courseId: number) {
    const draft = scheduleDrafts[courseId] ?? {
      day: 0,
      start: "08:00",
      end: "09:00",
      classroom: "",
    };
    setErrorMsg(null);
    try {
      await api.addCourseSchedule(courseId, {
        day_of_week: draft.day,
        start_time: draft.start,
        end_time: draft.end,
        classroom: draft.classroom.trim() || null,
      });
      setScheduleDrafts((prev) => ({
        ...prev,
        [courseId]: { ...draft, classroom: "" },
      }));
      await loadAcademicData();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Error agregando horario.");
    }
  }

  async function handleDeleteSchedule(scheduleId: number) {
    setErrorMsg(null);
    try {
      await api.deleteSchedule(scheduleId);
      await loadAcademicData();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Error eliminando horario.");
    }
  }

  async function handleDeleteCourse(courseId: number) {
    setErrorMsg(null);
    try {
      await api.deleteCourse(courseId);
      await Promise.all([loadAcademicData(), onRefreshOrg()]);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Error eliminando asignación.");
    }
  }

  async function handleGenerateTodaySessions() {
    setErrorMsg(null);
    setStatusMsg(null);
    try {
      const res = await api.generateAcademicSessions({
        organization_id: organization.id,
        target_date: getTodayIso(),
      });
      setStatusMsg(
        `Sesiones del ${res.target_date}: ${res.created_count} creadas, ${res.existing_count} ya existían.`
      );
      await onRefreshOrg();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "No se pudieron generar las sesiones.");
    }
  }

  async function handleOpenCourseKiosk(courseId: number) {
    setErrorMsg(null);
    try {
      const sess = await api.startCourseSession(courseId, { session_date: getTodayIso() });
      await onRefreshOrg();
      onOpenSessionInKiosk(sess.id);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "No se pudo abrir la sesión en Kiosco.");
    }
  }

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <GraduationCap className="w-6 h-6 text-indigo-400" />
            Estructura Académica y Estadísticas
          </h2>
          <p className="text-sm text-slate-400">
            Jerarquía: Institución → Carrera → Grupo → Materias, Profesores y Horarios
          </p>
        </div>

        <button
          type="button"
          onClick={() => void handleGenerateTodaySessions()}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-semibold"
        >
          <CalendarCheck className="w-4 h-4" />
          Generar sesiones de hoy
        </button>
      </div>

      {/* Sub-pestañas */}
      <div className="flex flex-wrap gap-2 bg-slate-900 border border-slate-800 rounded-xl p-1.5 w-fit">
        {[
          { id: "structure" as const, label: "Carreras y Grupos", icon: Layers },
          { id: "courses" as const, label: "Materias y Horarios", icon: BookOpen },
          { id: "stats" as const, label: "Estadísticas", icon: BarChart3 },
        ].map((tab) => {
          const Icon = tab.icon;
          const active = subTab === tab.id;
          return (
            <button
              key={tab.id}
              type="button"
              onClick={() => setSubTab(tab.id)}
              className={`inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                active ? "bg-indigo-600 text-white" : "text-slate-300 hover:bg-slate-800"
              }`}
            >
              <Icon className="w-4 h-4" />
              {tab.label}
            </button>
          );
        })}
      </div>

      {statusMsg && (
        <div className="rounded-xl bg-emerald-500/15 border border-emerald-500/40 px-4 py-3 text-sm text-emerald-200">
          {statusMsg}
        </div>
      )}
      {errorMsg && (
        <div className="rounded-xl bg-red-500/15 border border-red-500/40 px-4 py-3 text-sm text-red-200">
          {errorMsg}
        </div>
      )}

      {loading ? (
        <div className="py-10 text-center text-sm text-slate-400">Cargando estructura académica...</div>
      ) : (
        <>
          {subTab === "structure" && (
            <div className="space-y-6">
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Alta de Carrera */}
                <form
                  onSubmit={handleCreateCareer}
                  className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-3"
                >
                  <h3 className="font-semibold text-base">Nueva Carrera</h3>
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
                    <input
                      type="text"
                      required
                      value={careerName}
                      onChange={(e) => setCareerName(e.target.value)}
                      placeholder="Ej. Ingeniería en Software"
                      className="sm:col-span-2 bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                    />
                    <input
                      type="text"
                      required
                      value={careerCode}
                      onChange={(e) => setCareerCode(e.target.value)}
                      placeholder="Código (ISW)"
                      className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm uppercase"
                    />
                  </div>
                  <div className="flex gap-2.5">
                    <input
                      type="text"
                      value={careerDesc}
                      onChange={(e) => setCareerDesc(e.target.value)}
                      placeholder="Descripción opcional"
                      className="flex-1 bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                    />
                    <button
                      type="submit"
                      className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-sm font-semibold"
                    >
                      <Plus className="w-4 h-4" />
                      Crear Carrera
                    </button>
                  </div>
                </form>

                {/* Alta de Grupo Académico */}
                <form
                  onSubmit={handleCreateGroup}
                  className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-3"
                >
                  <h3 className="font-semibold text-base">Nuevo Grupo Académico</h3>
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
                    <input
                      type="text"
                      required
                      value={groupName}
                      onChange={(e) => setGroupName(e.target.value)}
                      placeholder="Nombre (Ej. 21026 IS)"
                      className="sm:col-span-2 bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                    />
                    <input
                      type="text"
                      required
                      value={groupCode}
                      onChange={(e) => setGroupCode(e.target.value)}
                      placeholder="Código"
                      className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                    />
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
                    <select
                      value={groupCareerId}
                      onChange={(e) => setGroupCareerId(e.target.value)}
                      className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                    >
                      <option value="">Sin carrera vinculada</option>
                      {careers.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.name} ({c.code})
                        </option>
                      ))}
                    </select>
                    <input
                      type="text"
                      value={groupSemester}
                      onChange={(e) => setGroupSemester(e.target.value)}
                      placeholder="Semestre / Cuatrimestre"
                      className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                    />
                    <button
                      type="submit"
                      className="inline-flex items-center justify-center gap-1.5 px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-sm font-semibold"
                    >
                      <Plus className="w-4 h-4" />
                      Crear Grupo
                    </button>
                  </div>
                </form>
              </div>

              {/* Árbol Carrera -> Grupos */}
              <div className="space-y-4">
                {careers.length === 0 ? (
                  <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 text-center text-sm text-slate-400">
                    Aún no hay carreras registradas. Crea la primera carrera arriba y vincula sus grupos.
                  </div>
                ) : (
                  careers.map((career) => {
                    const careerGroups = groups.filter((g) => g.career_id === career.id);
                    return (
                      <div
                        key={career.id}
                        className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-3"
                      >
                        <div className="flex items-start justify-between gap-4">
                          <div>
                            <div className="flex items-center gap-2">
                              <span className="px-2 py-0.5 rounded bg-indigo-500/20 text-indigo-300 text-xs font-semibold">
                                {career.code}
                              </span>
                              <h4 className="text-base font-bold">{career.name}</h4>
                            </div>
                            {career.description && (
                              <p className="text-xs text-slate-400 mt-1">{career.description}</p>
                            )}
                          </div>
                          <button
                            type="button"
                            onClick={() => void handleDeleteCareer(career.id)}
                            className="p-1.5 rounded-lg text-slate-400 hover:text-red-400 hover:bg-red-500/10"
                            title="Eliminar carrera"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>

                        {careerGroups.length === 0 ? (
                          <p className="text-xs text-slate-500 italic">
                            Sin grupos vinculados todavía.
                          </p>
                        ) : (
                          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                            {careerGroups.map((g) => (
                              <div
                                key={g.id}
                                className="rounded-xl bg-slate-800/60 border border-slate-700/70 p-3.5 flex items-center justify-between gap-2"
                              >
                                <div>
                                  <p className="text-sm font-semibold">
                                    {g.name}{" "}
                                    <span className="text-xs font-normal text-slate-400">
                                      ({g.code})
                                    </span>
                                  </p>
                                  <p className="text-xs text-slate-400 mt-0.5">
                                    {g.semester ? `${g.semester} · ` : ""}
                                    {g.members_count} alumnos · {g.courses_count} materias
                                  </p>
                                </div>
                                <button
                                  type="button"
                                  onClick={() => void handleDeleteGroup(g.id)}
                                  className="p-1 text-slate-500 hover:text-red-400"
                                  title="Eliminar grupo"
                                >
                                  <Trash2 className="w-3.5 h-3.5" />
                                </button>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })
                )}

                {groups.some((g) => g.career_id === null) && (
                  <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-3">
                    <h4 className="text-sm font-semibold text-slate-300">Grupos sin carrera asignada</h4>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      {groups
                        .filter((g) => g.career_id === null)
                        .map((g) => (
                          <div
                            key={g.id}
                            className="rounded-xl bg-slate-800/50 border border-slate-700/60 p-3 flex flex-wrap items-center justify-between gap-2"
                          >
                            <div>
                              <p className="text-sm font-medium">
                                {g.name} <span className="text-xs text-slate-400">({g.code})</span>
                              </p>
                              <p className="text-xs text-slate-400">
                                {g.members_count} alumnos · {g.courses_count} materias
                              </p>
                            </div>
                            <select
                              defaultValue=""
                              onChange={(e) => void handleLinkGroupCareer(g.id, e.target.value)}
                              className="bg-slate-900 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs"
                            >
                              <option value="">Asignar carrera...</option>
                              {careers.map((c) => (
                                <option key={c.id} value={c.id}>
                                  {c.name}
                                </option>
                              ))}
                            </select>
                          </div>
                        ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {subTab === "courses" && (
            <div className="space-y-6">
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Catálogo de Asignaturas */}
                <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4">
                  <h3 className="font-semibold text-base">Catálogo de Asignaturas</h3>
                  <form onSubmit={handleCreateSubject} className="space-y-2.5">
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
                      <input
                        type="text"
                        required
                        value={subjectName}
                        onChange={(e) => setSubjectName(e.target.value)}
                        placeholder="Ej. Arquitectura de Software"
                        className="sm:col-span-2 bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                      />
                      <input
                        type="text"
                        required
                        value={subjectCode}
                        onChange={(e) => setSubjectCode(e.target.value)}
                        placeholder="Clave (ARQ-101)"
                        className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm uppercase"
                      />
                    </div>
                    <div className="flex gap-2.5">
                      <select
                        value={subjectCareerId}
                        onChange={(e) => setSubjectCareerId(e.target.value)}
                        className="flex-1 bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                      >
                        <option value="">Carrera general / Todas</option>
                        {careers.map((c) => (
                          <option key={c.id} value={c.id}>
                            {c.name}
                          </option>
                        ))}
                      </select>
                      <button
                        type="submit"
                        className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-sm font-semibold"
                      >
                        <Plus className="w-4 h-4" />
                        Agregar
                      </button>
                    </div>
                  </form>

                  <div className="space-y-2 max-h-56 overflow-y-auto">
                    {subjects.map((subj) => (
                      <div
                        key={subj.id}
                        className="flex items-center justify-between px-3 py-2 rounded-xl bg-slate-800/50 border border-slate-800"
                      >
                        <div>
                          <p className="text-sm font-medium">
                            {subj.name}{" "}
                            <span className="text-xs text-indigo-300">({subj.code})</span>
                          </p>
                          {subj.career_name && (
                            <p className="text-[11px] text-slate-400">{subj.career_name}</p>
                          )}
                        </div>
                        <button
                          type="button"
                          onClick={() => void handleDeleteSubject(subj.id)}
                          className="p-1 text-slate-400 hover:text-red-400"
                          title="Eliminar asignatura"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    ))}
                    {subjects.length === 0 && (
                      <p className="text-xs text-slate-500 text-center py-4">
                        Agrega las materias que se imparten en la institución.
                      </p>
                    )}
                  </div>
                </div>

                {/* Vincular Grupo + Materia + Profesor + Horario */}
                <form
                  onSubmit={handleCreateCourse}
                  className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-3"
                >
                  <h3 className="font-semibold text-base">
                    Asignar Materia y Profesor a un Grupo
                  </h3>

                  {teachers.filter((t) => t.role === "teacher").length === 0 && (
                    <div className="rounded-xl bg-amber-500/10 border border-amber-500/30 px-3 py-2 text-xs text-amber-200">
                      Tip: crea cuentas con rol <strong>Profesor</strong> en la pestaña{" "}
                      <em>Seguridad y Usuarios</em> para que cada docente vea únicamente sus materias.
                    </div>
                  )}

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                    <div>
                      <label className="block text-[11px] text-slate-400 mb-1">Grupo</label>
                      <select
                        required
                        value={courseGroupId}
                        onChange={(e) => setCourseGroupId(e.target.value)}
                        className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                      >
                        <option value="">Selecciona grupo...</option>
                        {groups.map((g) => (
                          <option key={g.id} value={g.id}>
                            {g.name} ({g.code})
                          </option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="block text-[11px] text-slate-400 mb-1">Asignatura</label>
                      <select
                        required
                        value={courseSubjectId}
                        onChange={(e) => setCourseSubjectId(e.target.value)}
                        className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                      >
                        <option value="">Selecciona materia...</option>
                        {subjects.map((s) => (
                          <option key={s.id} value={s.id}>
                            {s.name} ({s.code})
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                    <div>
                      <label className="block text-[11px] text-slate-400 mb-1">Profesor</label>
                      <select
                        value={courseTeacherId}
                        onChange={(e) => setCourseTeacherId(e.target.value)}
                        className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                      >
                        <option value="">Sin asignar aún</option>
                        {teachers.map((t) => (
                          <option key={t.id} value={t.id}>
                            {t.full_name} ({t.role === "teacher" ? "Profesor" : "Admin"})
                          </option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="block text-[11px] text-slate-400 mb-1">Ciclo / Periodo</label>
                      <input
                        type="text"
                        value={courseTerm}
                        onChange={(e) => setCourseTerm(e.target.value)}
                        placeholder="Ej. 2026-3"
                        className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                      />
                    </div>
                  </div>

                  <div className="pt-2 border-t border-slate-800">
                    <p className="text-xs font-semibold text-slate-300 mb-2">Horario inicial de clase</p>
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                      <select
                        value={initDay}
                        onChange={(e) => setInitDay(Number(e.target.value))}
                        className="bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-2 text-xs"
                      >
                        {WEEKDAYS.map((d) => (
                          <option key={d.value} value={d.value}>
                            {d.label}
                          </option>
                        ))}
                      </select>
                      <input
                        type="time"
                        required
                        value={initStart}
                        onChange={(e) => setInitStart(e.target.value)}
                        className="bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-2 text-xs"
                      />
                      <input
                        type="time"
                        required
                        value={initEnd}
                        onChange={(e) => setInitEnd(e.target.value)}
                        className="bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-2 text-xs"
                      />
                      <input
                        type="text"
                        value={initClassroom}
                        onChange={(e) => setInitClassroom(e.target.value)}
                        placeholder="Aula / Lab"
                        className="bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-2 text-xs"
                      />
                    </div>
                  </div>

                  <button
                    type="submit"
                    className="w-full py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-sm font-semibold"
                  >
                    Asignar Materia al Grupo
                  </button>
                </form>
              </div>

              {/* Lista de asignaciones activas con bloques de horario */}
              <div className="space-y-3">
                <h3 className="font-semibold text-base">
                  Asignaciones y Horarios ({courses.length})
                </h3>

                {courses.length === 0 ? (
                  <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 text-center text-sm text-slate-400">
                    No hay asignaturas vinculadas a grupos todavía.
                  </div>
                ) : (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {courses.map((course) => {
                      const draft = scheduleDrafts[course.id] ?? {
                        day: 0,
                        start: "08:00",
                        end: "09:00",
                        classroom: "",
                      };
                      return (
                        <div
                          key={course.id}
                          className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-3"
                        >
                          <div className="flex items-start justify-between gap-2">
                            <div>
                              <div className="flex items-center gap-2 flex-wrap">
                                <span className="px-2 py-0.5 rounded bg-indigo-500/20 text-indigo-300 text-xs font-semibold">
                                  {course.subject_code}
                                </span>
                                <h4 className="font-bold text-base">{course.subject_name}</h4>
                              </div>
                              <p className="text-xs text-slate-400 mt-1">
                                Grupo: <strong className="text-slate-200">{course.group_name}</strong>
                                {course.career_name ? ` · ${course.career_name}` : ""} ·{" "}
                                {course.students_count} alumnos heredados
                              </p>
                            </div>

                            <div className="flex items-center gap-1.5">
                              <button
                                type="button"
                                onClick={() => void handleOpenCourseKiosk(course.id)}
                                className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-emerald-600/20 border border-emerald-500/40 hover:bg-emerald-600/30 text-emerald-300 text-xs font-semibold"
                                title="Abrir pase de lista en Kiosco"
                              >
                                <ScanFace className="w-3.5 h-3.5" />
                                Abrir pase
                              </button>
                              <button
                                type="button"
                                onClick={() => void handleDeleteCourse(course.id)}
                                className="p-1.5 rounded-lg text-slate-400 hover:text-red-400 hover:bg-red-500/10"
                                title="Eliminar asignación"
                              >
                                <Trash2 className="w-4 h-4" />
                              </button>
                            </div>
                          </div>

                          <div className="flex items-center gap-2 text-xs">
                            <span className="text-slate-400">Profesor:</span>
                            <select
                              value={course.teacher_user_id ?? ""}
                              onChange={(e) => void handleReassignTeacher(course.id, e.target.value)}
                              className="flex-1 bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-1 text-xs"
                            >
                              <option value="">Sin profesor asignado</option>
                              {teachers.map((t) => (
                                <option key={t.id} value={t.id}>
                                  {t.full_name}
                                </option>
                              ))}
                            </select>
                          </div>

                          {/* Bloques de horario */}
                          <div className="space-y-1.5 pt-1">
                            {course.schedules.map((sl) => (
                              <div
                                key={sl.id}
                                className="flex items-center justify-between px-3 py-1.5 rounded-lg bg-slate-800/60 text-xs"
                              >
                                <span className="flex items-center gap-2">
                                  <Clock className="w-3.5 h-3.5 text-indigo-400" />
                                  <strong>{dayLabel(sl.day_of_week)}</strong> {sl.start_time} –{" "}
                                  {sl.end_time}
                                  {sl.classroom && (
                                    <span className="text-slate-400">· {sl.classroom}</span>
                                  )}
                                </span>
                                <button
                                  type="button"
                                  onClick={() => void handleDeleteSchedule(sl.id)}
                                  className="text-slate-500 hover:text-red-400"
                                  title="Quitar bloque"
                                >
                                  <Trash2 className="w-3.5 h-3.5" />
                                </button>
                              </div>
                            ))}

                            <div className="grid grid-cols-5 gap-1.5 pt-1">
                              <select
                                value={draft.day}
                                onChange={(e) =>
                                  setScheduleDrafts((prev) => ({
                                    ...prev,
                                    [course.id]: { ...draft, day: Number(e.target.value) },
                                  }))
                                }
                                className="col-span-2 bg-slate-800 border border-slate-700 rounded px-2 py-1 text-[11px]"
                              >
                                {WEEKDAYS.map((d) => (
                                  <option key={d.value} value={d.value}>
                                    {d.label}
                                  </option>
                                ))}
                              </select>
                              <input
                                type="time"
                                value={draft.start}
                                onChange={(e) =>
                                  setScheduleDrafts((prev) => ({
                                    ...prev,
                                    [course.id]: { ...draft, start: e.target.value },
                                  }))
                                }
                                className="bg-slate-800 border border-slate-700 rounded px-1.5 py-1 text-[11px]"
                              />
                              <input
                                type="time"
                                value={draft.end}
                                onChange={(e) =>
                                  setScheduleDrafts((prev) => ({
                                    ...prev,
                                    [course.id]: { ...draft, end: e.target.value },
                                  }))
                                }
                                className="bg-slate-800 border border-slate-700 rounded px-1.5 py-1 text-[11px]"
                              />
                              <button
                                type="button"
                                onClick={() => void handleAddSchedule(course.id)}
                                className="inline-flex items-center justify-center rounded bg-slate-700 hover:bg-indigo-600 text-[11px] font-semibold px-2 py-1"
                              >
                                + Hora
                              </button>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          )}

          {subTab === "stats" && (
            <div className="space-y-6">
              {/* Filtros */}
              <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4 grid grid-cols-1 sm:grid-cols-5 gap-3 items-end">
                <div>
                  <label className="block text-[11px] text-slate-400 mb-1">Desde</label>
                  <input
                    type="date"
                    value={statsDateFrom}
                    onChange={(e) => setStatsDateFrom(e.target.value)}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-xs"
                  />
                </div>
                <div>
                  <label className="block text-[11px] text-slate-400 mb-1">Hasta</label>
                  <input
                    type="date"
                    value={statsDateTo}
                    onChange={(e) => setStatsDateTo(e.target.value)}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-xs"
                  />
                </div>
                <div>
                  <label className="block text-[11px] text-slate-400 mb-1">Carrera</label>
                  <select
                    value={statsCareerId}
                    onChange={(e) => setStatsCareerId(e.target.value)}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-xs"
                  >
                    <option value="">Todas</option>
                    {careers.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-[11px] text-slate-400 mb-1">Grupo</label>
                  <select
                    value={statsGroupId}
                    onChange={(e) => setStatsGroupId(e.target.value)}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-xs"
                  >
                    <option value="">Todos</option>
                    {groups.map((g) => (
                      <option key={g.id} value={g.id}>
                        {g.name}
                      </option>
                    ))}
                  </select>
                </div>
                <button
                  type="button"
                  onClick={() => void loadStats()}
                  className="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-xs font-semibold"
                >
                  Aplicar filtros
                </button>
              </div>

              {stats && (
                <>
                  {/* KPIs globales */}
                  <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
                    {[
                      { label: "Carreras", value: stats.summary.total_careers },
                      { label: "Grupos", value: stats.summary.total_groups },
                      { label: "Materias activas", value: stats.summary.total_courses },
                      { label: "Sesiones", value: stats.summary.total_sessions },
                      {
                        label: "Asistencia global",
                        value: `${stats.summary.overall_attendance_rate.toFixed(1)}%`,
                      },
                    ].map((kpi) => (
                      <div
                        key={kpi.label}
                        className="bg-slate-900 border border-slate-800 rounded-2xl p-4"
                      >
                        <p className="text-xs text-slate-400">{kpi.label}</p>
                        <p className="text-2xl font-bold mt-1">{kpi.value}</p>
                      </div>
                    ))}
                  </div>

                  {/* Por Asignatura */}
                  <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-3">
                    <h3 className="font-semibold text-base">Asistencia por Asignatura</h3>
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm text-left">
                        <thead className="text-xs text-slate-400 border-b border-slate-800">
                          <tr>
                            <th className="py-2 pr-3">Materia</th>
                            <th className="py-2 pr-3">Grupo</th>
                            <th className="py-2 pr-3">Profesor</th>
                            <th className="py-2 pr-3">Sesiones</th>
                            <th className="py-2 pr-3">Asistencias</th>
                            <th className="py-2 pr-3">Retardos</th>
                            <th className="py-2 pr-3">Faltas</th>
                            <th className="py-2 pr-3">% Asistencia</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-800/80">
                          {stats.by_subject.map((row) => (
                            <tr key={row.course_assignment_id}>
                              <td className="py-2.5 pr-3">
                                <span className="font-medium">{row.subject_name}</span>{" "}
                                <span className="text-xs text-slate-400">({row.subject_code})</span>
                              </td>
                              <td className="py-2.5 pr-3 text-xs">{row.group_name}</td>
                              <td className="py-2.5 pr-3 text-xs text-slate-300">
                                {row.teacher_name ?? "—"}
                              </td>
                              <td className="py-2.5 pr-3 text-xs">{row.sessions_count}</td>
                              <td className="py-2.5 pr-3 text-xs text-emerald-300">
                                {row.present_count} / {row.expected_records}
                              </td>
                              <td className="py-2.5 pr-3 text-xs text-amber-300">
                                {row.late_count}
                              </td>
                              <td className="py-2.5 pr-3 text-xs text-red-300">
                                {row.absent_count}
                              </td>
                              <td className="py-2.5 pr-3 font-semibold text-indigo-300">
                                {row.attendance_rate.toFixed(1)}%
                              </td>
                            </tr>
                          ))}
                          {stats.by_subject.length === 0 && (
                            <tr>
                              <td colSpan={8} className="py-6 text-center text-xs text-slate-500">
                                No hay asignaturas para mostrar con estos filtros.
                              </td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                  </div>

                  {/* Consolidado por Grupo */}
                  <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-3">
                    <h3 className="font-semibold text-base">
                      Consolidado por Grupo (todas sus materias)
                    </h3>
                    <div className="space-y-3">
                      {stats.by_group.map((grp) => {
                        const expanded = Boolean(expandedGroupIds[grp.group_id]);
                        return (
                          <div
                            key={grp.group_id}
                            className="rounded-xl bg-slate-800/40 border border-slate-800 overflow-hidden"
                          >
                            <button
                              type="button"
                              onClick={() =>
                                setExpandedGroupIds((prev) => ({
                                  ...prev,
                                  [grp.group_id]: !expanded,
                                }))
                              }
                              className="w-full px-4 py-3 flex flex-wrap items-center justify-between gap-3 text-left hover:bg-slate-800/70"
                            >
                              <div>
                                <p className="font-semibold text-sm">
                                  {grp.group_name}{" "}
                                  <span className="text-xs text-slate-400">({grp.group_code})</span>
                                </p>
                                <p className="text-xs text-slate-400">
                                  {grp.career_name ?? "Sin carrera"} · {grp.subjects_count} materias ·{" "}
                                  {grp.students_count} alumnos · {grp.total_sessions} sesiones
                                </p>
                              </div>
                              <div className="flex items-center gap-4 text-xs">
                                <span className="text-emerald-300">
                                  {grp.total_present}/{grp.total_expected} asist.
                                </span>
                                <span className="px-2.5 py-1 rounded-full bg-indigo-500/20 text-indigo-300 font-bold">
                                  {grp.overall_attendance_rate.toFixed(1)}%
                                </span>
                                {expanded ? (
                                  <ChevronUp className="w-4 h-4 text-slate-400" />
                                ) : (
                                  <ChevronDown className="w-4 h-4 text-slate-400" />
                                )}
                              </div>
                            </button>

                            {expanded && (
                              <div className="px-4 pb-3 border-t border-slate-800/80 pt-2.5">
                                {grp.students_breakdown.length === 0 ? (
                                  <p className="text-xs text-slate-500">
                                    Sin alumnos asignados a este grupo.
                                  </p>
                                ) : (
                                  <table className="w-full text-xs">
                                    <thead className="text-slate-400 border-b border-slate-800">
                                      <tr>
                                        <th className="py-1.5 text-left">Matrícula</th>
                                        <th className="py-1.5 text-left">Alumno</th>
                                        <th className="py-1.5 text-left">Asistencias</th>
                                        <th className="py-1.5 text-left">Retardos</th>
                                        <th className="py-1.5 text-left">Faltas</th>
                                        <th className="py-1.5 text-left">% General</th>
                                      </tr>
                                    </thead>
                                    <tbody className="divide-y divide-slate-800/60">
                                      {grp.students_breakdown.map((st) => (
                                        <tr key={st.person_id}>
                                          <td className="py-1.5 font-mono text-slate-300">
                                            {st.external_id}
                                          </td>
                                          <td className="py-1.5 font-medium">{st.full_name}</td>
                                          <td className="py-1.5 text-emerald-300">
                                            {st.present_count} / {st.expected_records}
                                          </td>
                                          <td className="py-1.5 text-amber-300">{st.late_count}</td>
                                          <td className="py-1.5 text-red-300">{st.absent_count}</td>
                                          <td className="py-1.5 font-semibold text-indigo-300">
                                            {st.attendance_rate.toFixed(1)}%
                                          </td>
                                        </tr>
                                      ))}
                                    </tbody>
                                  </table>
                                )}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
