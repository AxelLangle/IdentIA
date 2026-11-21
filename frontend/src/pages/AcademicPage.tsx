import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  ArrowUpDown,
  BarChart3,
  BookOpen,
  CalendarCheck,
  ChevronDown,
  ChevronUp,
  Clock,
  GraduationCap,
  Layers,
  Lock,
  Pencil,
  Plus,
  ScanFace,
  Trash2,
  X,
} from "lucide-react";
import { PasswordInput } from "../components/PasswordInput";
import {
  ACADEMIC_PERIOD_OPTIONS,
  comparePeriodsNatural,
  formatGroupPeriodLabel,
  getPeriodMeta,
} from "../lib/academicPeriods";
import { api } from "../lib/api";
import type {
  AcademicPeriodType,
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
type SubjectSortField = "career_period" | "period_career" | "rate" | "subject";
type GroupSortField = "career_period" | "period_career" | "rate" | "group";

interface PendingScheduleDraft {
  day_of_week: number;
  start_time: string;
  end_time: string;
  classroom: string;
}

type PendingPeriodChange =
  | {
      scope: "organization";
      nextPeriodType: AcademicPeriodType;
      summary: string;
    }
  | {
      scope: "career";
      careerId: number;
      careerName: string;
      nextPeriodType: string;
      summary: string;
    }
  | {
      scope: "group";
      groupId: number;
      groupName: string;
      nextPeriodType: string;
      semester: string | null;
      classroom: string | null;
      summary: string;
    };

const WEEKDAYS = [
  { value: 0, short: "Lun", mini: "L", label: "Lunes" },
  { value: 1, short: "Mar", mini: "M", label: "Martes" },
  { value: 2, short: "Mié", mini: "X", label: "Miércoles" },
  { value: 3, short: "Jue", mini: "J", label: "Jueves" },
  { value: 4, short: "Vie", mini: "V", label: "Viernes" },
  { value: 5, short: "Sáb", mini: "S", label: "Sábado" },
  { value: 6, short: "Dom", mini: "D", label: "Domingo" },
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

function getDefaultWeekday(): number {
  return new Date().getDay() === 0 ? 6 : new Date().getDay() - 1;
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

  // Periodo académico general de la institución
  const [orgPeriodType, setOrgPeriodType] = useState<AcademicPeriodType>(
    organization.academic_period_type ?? "semestral"
  );

  // Alta de carrera
  const [careerName, setCareerName] = useState("");
  const [careerCode, setCareerCode] = useState("");
  const [careerDesc, setCareerDesc] = useState("");
  const [careerPeriodType, setCareerPeriodType] = useState<string>("");

  // Alta de grupo académico
  const [groupName, setGroupName] = useState("");
  const [groupCode, setGroupCode] = useState("");
  const [groupCareerId, setGroupCareerId] = useState<string>("");
  const [groupSemester, setGroupSemester] = useState("");
  const [groupPeriodType, setGroupPeriodType] = useState<string>("");
  const [groupDefaultClassroom, setGroupDefaultClassroom] = useState("");

  // Edición rápida de grupo (aula fija / periodo)
  const [editingGroupId, setEditingGroupId] = useState<number | null>(null);
  const [editGroupSemester, setEditGroupSemester] = useState("");
  const [editGroupPeriodType, setEditGroupPeriodType] = useState<string>("");
  const [editGroupClassroom, setEditGroupClassroom] = useState("");

  // Autorización de administrador para cambiar tipo de periodo
  const [pendingPeriodChange, setPendingPeriodChange] = useState<PendingPeriodChange | null>(null);
  const [periodAuthSecret, setPeriodAuthSecret] = useState("");
  const [periodAuthError, setPeriodAuthError] = useState<string | null>(null);
  const [periodAuthSubmitting, setPeriodAuthSubmitting] = useState(false);

  // Alta de asignatura
  const [subjectName, setSubjectName] = useState("");
  const [subjectCode, setSubjectCode] = useState("");
  const [subjectCareerId, setSubjectCareerId] = useState<string>("");

  // Alta de curso (Grupo + Materia + Profesor + horarios multi-día)
  const [courseGroupId, setCourseGroupId] = useState<string>("");
  const [courseSubjectId, setCourseSubjectId] = useState<string>("");
  const [courseTeacherId, setCourseTeacherId] = useState<string>("");
  const [courseTerm, setCourseTerm] = useState("");
  const [selectedDays, setSelectedDays] = useState<number[]>([getDefaultWeekday()]);
  const [initStart, setInitStart] = useState("10:00");
  const [initEnd, setInitEnd] = useState("11:00");
  const [initClassroom, setInitClassroom] = useState("");
  const [pendingSchedules, setPendingSchedules] = useState<PendingScheduleDraft[]>([]);

  // Bloques horarios inline por curso existente (multi-día + aula prellenada editable)
  const [scheduleDrafts, setScheduleDrafts] = useState<
    Record<number, { days: number[]; start: string; end: string; classroom?: string }>
  >({});

  // Filtros y ordenamiento de estadísticas
  const [statsDateFrom, setStatsDateFrom] = useState("");
  const [statsDateTo, setStatsDateTo] = useState("");
  const [statsCareerId, setStatsCareerId] = useState<string>("");
  const [statsGroupId, setStatsGroupId] = useState<string>("");
  const [expandedGroupIds, setExpandedGroupIds] = useState<Record<number, boolean>>({});
  const [subjectSortBy, setSubjectSortBy] = useState<SubjectSortField>("career_period");
  const [subjectSortAsc, setSubjectSortAsc] = useState(true);
  const [groupSortBy, setGroupSortBy] = useState<GroupSortField>("career_period");
  const [groupSortAsc, setGroupSortAsc] = useState(true);

  useEffect(() => {
    setOrgPeriodType(organization.academic_period_type ?? "semestral");
  }, [organization.academic_period_type, organization.id]);

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
      setTeachers(
        usersList.filter((u) => u.is_active && (u.role === "teacher" || u.role === "org_admin"))
      );
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

  function requestOrganizationPeriodChange(e: FormEvent) {
    e.preventDefault();
    setErrorMsg(null);
    setStatusMsg(null);
    const currentOrgPeriod = organization.academic_period_type ?? "semestral";
    if (orgPeriodType === currentOrgPeriod) {
      setStatusMsg(`El periodo general actual ya es ${getPeriodMeta(orgPeriodType).label}.`);
      return;
    }
    setPeriodAuthSecret("");
    setPeriodAuthError(null);
    setPendingPeriodChange({
      scope: "organization",
      nextPeriodType: orgPeriodType,
      summary: `Institución "${organization.name}": ${getPeriodMeta(currentOrgPeriod).label} → ${getPeriodMeta(orgPeriodType).label}`,
    });
  }

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
        period_type: careerPeriodType ? (careerPeriodType as AcademicPeriodType) : null,
      });
      setCareerName("");
      setCareerCode("");
      setCareerDesc("");
      setCareerPeriodType("");
      setStatusMsg("Carrera registrada.");
      await loadAcademicData();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Error creando carrera.");
    }
  }

  function requestCareerPeriodChange(career: Career, nextValue: string) {
    const currentVal = career.period_type ?? "";
    if (nextValue === currentVal) return;
    setErrorMsg(null);
    setStatusMsg(null);
    const nextLabel = nextValue
      ? getPeriodMeta(nextValue).label
      : `Heredar general (${getPeriodMeta(organization.academic_period_type).label})`;
    setPeriodAuthSecret("");
    setPeriodAuthError(null);
    setPendingPeriodChange({
      scope: "career",
      careerId: career.id,
      careerName: career.name,
      nextPeriodType: nextValue,
      summary: `Carrera "${career.name}": ${getPeriodMeta(career.effective_period_type).label} → ${nextLabel}`,
    });
  }

  async function handleConfirmPeriodChange(e: FormEvent) {
    e.preventDefault();
    if (!pendingPeriodChange) return;
    setPeriodAuthError(null);
    setPeriodAuthSubmitting(true);
    try {
      if (pendingPeriodChange.scope === "organization") {
        await api.updateOrganization(organization.id, {
          academic_period_type: pendingPeriodChange.nextPeriodType,
          authorization_secret: periodAuthSecret,
        });
        setStatusMsg(
          `Periodo académico general actualizado a ${getPeriodMeta(pendingPeriodChange.nextPeriodType).label}.`
        );
      } else if (pendingPeriodChange.scope === "career") {
        await api.updateCareer(pendingPeriodChange.careerId, {
          period_type: pendingPeriodChange.nextPeriodType
            ? (pendingPeriodChange.nextPeriodType as AcademicPeriodType)
            : null,
          authorization_secret: periodAuthSecret,
        });
        setStatusMsg(`Tipo de periodo de "${pendingPeriodChange.careerName}" actualizado.`);
      } else {
        await api.updateGroup(pendingPeriodChange.groupId, {
          semester: pendingPeriodChange.semester,
          default_classroom: pendingPeriodChange.classroom,
          period_type: pendingPeriodChange.nextPeriodType
            ? (pendingPeriodChange.nextPeriodType as AcademicPeriodType)
            : null,
          authorization_secret: periodAuthSecret,
        });
        setEditingGroupId(null);
        setStatusMsg(`Tipo de periodo de "${pendingPeriodChange.groupName}" actualizado.`);
      }
      setPendingPeriodChange(null);
      setPeriodAuthSecret("");
      await Promise.all([onRefreshOrg(), loadAcademicData()]);
    } catch (err) {
      setPeriodAuthError(
        err instanceof Error ? err.message : "No se pudo autorizar el cambio de periodo."
      );
    } finally {
      setPeriodAuthSubmitting(false);
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
        period_type: groupPeriodType ? (groupPeriodType as AcademicPeriodType) : null,
        default_classroom: groupDefaultClassroom.trim() || null,
        schedule_start: "07:00",
        schedule_end: "15:00",
      });
      setGroupName("");
      setGroupCode("");
      setGroupSemester("");
      setGroupPeriodType("");
      setGroupDefaultClassroom("");
      setStatusMsg("Grupo académico creado.");
      await Promise.all([onRefreshOrg(), loadAcademicData()]);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Error creando grupo.");
    }
  }

  function startEditGroup(g: Group) {
    setEditingGroupId(g.id);
    setEditGroupSemester(g.semester ?? "");
    setEditGroupPeriodType(g.custom_period_type ?? "");
    setEditGroupClassroom(g.default_classroom ?? "");
  }

  async function handleSaveGroupEdit(group: Group) {
    setErrorMsg(null);
    const currentCustom = group.custom_period_type ?? "";
    const trimmedSemester = editGroupSemester.trim() || null;
    const trimmedClassroom = editGroupClassroom.trim() || null;

    if (editGroupPeriodType !== currentCustom) {
      const nextLabel = editGroupPeriodType
        ? getPeriodMeta(editGroupPeriodType).label
        : "Heredar de carrera/institución";
      setPeriodAuthSecret("");
      setPeriodAuthError(null);
      setPendingPeriodChange({
        scope: "group",
        groupId: group.id,
        groupName: group.name,
        nextPeriodType: editGroupPeriodType,
        semester: trimmedSemester,
        classroom: trimmedClassroom,
        summary: `Grupo "${group.name}": ${getPeriodMeta(group.period_type).label} → ${nextLabel}`,
      });
      return;
    }

    try {
      await api.updateGroup(group.id, {
        semester: trimmedSemester,
        default_classroom: trimmedClassroom,
      });
      setEditingGroupId(null);
      await Promise.all([onRefreshOrg(), loadAcademicData()]);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "No se pudo actualizar el grupo.");
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

  function handleSelectCourseGroup(groupIdStr: string) {
    setCourseGroupId(groupIdStr);
    const selected = groups.find((g) => String(g.id) === groupIdStr);
    // Prellena el aula fija del grupo pero deja editarla libremente
    setInitClassroom(selected?.default_classroom ?? "");
  }

  function toggleSelectedDay(day: number) {
    setSelectedDays((prev) =>
      prev.includes(day) ? prev.filter((d) => d !== day) : [...prev, day].sort((a, b) => a - b)
    );
  }

  function appendSelectedDaysToPending() {
    if (selectedDays.length === 0) return;
    setPendingSchedules((prev) => {
      const next = [...prev];
      const existingKeys = new Set(
        next.map((s) => `${s.day_of_week}-${s.start_time}-${s.end_time}`)
      );
      for (const day of [...selectedDays].sort((a, b) => a - b)) {
        const key = `${day}-${initStart}-${initEnd}`;
        if (!existingKeys.has(key)) {
          next.push({
            day_of_week: day,
            start_time: initStart,
            end_time: initEnd,
            classroom: initClassroom.trim(),
          });
          existingKeys.add(key);
        }
      }
      return next;
    });
    setSelectedDays([]);
  }

  async function handleCreateCourse(e: FormEvent) {
    e.preventDefault();
    if (!courseGroupId || !courseSubjectId) return;
    setErrorMsg(null);
    setStatusMsg(null);

    const combined: PendingScheduleDraft[] = [...pendingSchedules];
    const seen = new Set(combined.map((s) => `${s.day_of_week}-${s.start_time}-${s.end_time}`));
    for (const day of [...selectedDays].sort((a, b) => a - b)) {
      const key = `${day}-${initStart}-${initEnd}`;
      if (!seen.has(key)) {
        combined.push({
          day_of_week: day,
          start_time: initStart,
          end_time: initEnd,
          classroom: initClassroom.trim(),
        });
        seen.add(key);
      }
    }

    if (combined.length === 0) {
      setErrorMsg("Selecciona al menos un día para el horario de la materia.");
      return;
    }

    try {
      await api.createCourse({
        organization_id: organization.id,
        group_id: Number(courseGroupId),
        subject_id: Number(courseSubjectId),
        teacher_user_id: courseTeacherId ? Number(courseTeacherId) : null,
        term: courseTerm.trim() || null,
        schedules: combined.map((sl) => ({
          day_of_week: sl.day_of_week,
          start_time: sl.start_time,
          end_time: sl.end_time,
          classroom: sl.classroom.trim() || null,
        })),
      });
      const grp = groups.find((g) => String(g.id) === courseGroupId);
      setPendingSchedules([]);
      setSelectedDays([getDefaultWeekday()]);
      setInitClassroom(grp?.default_classroom ?? "");
      setStatusMsg(
        `Asignatura vinculada al grupo con ${combined.length} bloque${combined.length === 1 ? "" : "s"} de horario.`
      );
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

  function getCourseScheduleDraft(course: CourseAssignment) {
    return (
      scheduleDrafts[course.id] ?? {
        days: [0],
        start: "08:00",
        end: "09:00",
        classroom: course.group_default_classroom ?? "",
      }
    );
  }

  function toggleInlineDraftDay(course: CourseAssignment, day: number) {
    const draft = getCourseScheduleDraft(course);
    const nextDays = draft.days.includes(day)
      ? draft.days.filter((d) => d !== day)
      : [...draft.days, day].sort((a, b) => a - b);
    setScheduleDrafts((prev) => ({
      ...prev,
      [course.id]: { ...draft, days: nextDays },
    }));
  }

  async function handleAddSchedulesToCourse(course: CourseAssignment) {
    const draft = getCourseScheduleDraft(course);
    if (draft.days.length === 0) {
      setErrorMsg("Marca al menos un día para agregar el horario.");
      return;
    }
    setErrorMsg(null);
    const resolvedClassroom = (draft.classroom ?? course.group_default_classroom ?? "").trim() || null;
    try {
      for (const day of draft.days) {
        await api.addCourseSchedule(course.id, {
          day_of_week: day,
          start_time: draft.start,
          end_time: draft.end,
          classroom: resolvedClassroom,
        });
      }
      setScheduleDrafts((prev) => ({
        ...prev,
        [course.id]: {
          ...draft,
          days: [],
          classroom: course.group_default_classroom ?? "",
        },
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

  const selectedCareerForNewGroup = careers.find((c) => String(c.id) === groupCareerId);
  const newGroupPeriodMeta = getPeriodMeta(
    groupPeriodType || selectedCareerForNewGroup?.effective_period_type || orgPeriodType
  );
  const orgPeriodMeta = getPeriodMeta(orgPeriodType);

  const sortedBySubject = stats
    ? [...stats.by_subject].sort((a, b) => {
        const dir = subjectSortAsc ? 1 : -1;
        let cmp = 0;
        if (subjectSortBy === "career_period") {
          cmp = (a.career_name ?? "ZZZ").localeCompare(b.career_name ?? "ZZZ", "es");
          if (cmp === 0) cmp = comparePeriodsNatural(a.semester, b.semester);
          if (cmp === 0) cmp = a.subject_name.localeCompare(b.subject_name, "es");
        } else if (subjectSortBy === "period_career") {
          cmp = comparePeriodsNatural(a.semester, b.semester);
          if (cmp === 0) cmp = (a.career_name ?? "ZZZ").localeCompare(b.career_name ?? "ZZZ", "es");
          if (cmp === 0) cmp = a.subject_name.localeCompare(b.subject_name, "es");
        } else if (subjectSortBy === "rate") {
          cmp = a.attendance_rate - b.attendance_rate;
        } else {
          cmp = a.subject_name.localeCompare(b.subject_name, "es");
        }
        return cmp * dir;
      })
    : [];

  const sortedByGroup = stats
    ? [...stats.by_group].sort((a, b) => {
        const dir = groupSortAsc ? 1 : -1;
        let cmp = 0;
        if (groupSortBy === "career_period") {
          cmp = (a.career_name ?? "ZZZ").localeCompare(b.career_name ?? "ZZZ", "es");
          if (cmp === 0) cmp = comparePeriodsNatural(a.semester, b.semester);
          if (cmp === 0) cmp = a.group_name.localeCompare(b.group_name, "es", { numeric: true });
        } else if (groupSortBy === "period_career") {
          cmp = comparePeriodsNatural(a.semester, b.semester);
          if (cmp === 0) cmp = (a.career_name ?? "ZZZ").localeCompare(b.career_name ?? "ZZZ", "es");
          if (cmp === 0) cmp = a.group_name.localeCompare(b.group_name, "es", { numeric: true });
        } else if (groupSortBy === "rate") {
          cmp = a.overall_attendance_rate - b.overall_attendance_rate;
        } else {
          cmp = a.group_name.localeCompare(b.group_name, "es", { numeric: true });
        }
        return cmp * dir;
      })
    : [];

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <GraduationCap className="w-6 h-6 text-indigo-400" />
            Estructura Académica y Estadísticas
          </h2>
          <p className="text-sm text-slate-400">
            Jerarquía: Institución ({orgPeriodMeta.label}) → Carrera → Grupo → Materias,
            Profesores y Horarios
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
              {/* Periodo general de la institución */}
              <form
                onSubmit={requestOrganizationPeriodChange}
                className="bg-slate-900 border border-slate-800 rounded-2xl p-4 flex flex-wrap items-center justify-between gap-4"
              >
                <div>
                  <h3 className="font-semibold text-sm flex items-center gap-1.5">
                    Periodo académico general de la institución
                    <span title="Requiere contraseña de administrador para cambiar">
                      <Lock className="w-3.5 h-3.5 text-amber-400" />
                    </span>
                  </h3>
                  <p className="text-xs text-slate-400">
                    Se hereda por defecto en carreras y grupos (cada carrera o grupo puede usar otro sistema; cambiarlo requiere contraseña admin).
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <select
                    value={orgPeriodType}
                    onChange={(e) => setOrgPeriodType(e.target.value as AcademicPeriodType)}
                    className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                  >
                    {ACADEMIC_PERIOD_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                  <button
                    type="submit"
                    disabled={orgPeriodType === (organization.academic_period_type ?? "semestral")}
                    className="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-xs font-semibold"
                  >
                    Cambiar periodo
                  </button>
                </div>
              </form>

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
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                    <input
                      type="text"
                      value={careerDesc}
                      onChange={(e) => setCareerDesc(e.target.value)}
                      placeholder="Descripción opcional"
                      className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                    />
                    <select
                      value={careerPeriodType}
                      onChange={(e) => setCareerPeriodType(e.target.value)}
                      className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                    >
                      <option value="">Usar general ({orgPeriodMeta.label})</option>
                      {ACADEMIC_PERIOD_OPTIONS.map((opt) => (
                        <option key={opt.value} value={opt.value}>
                          {opt.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="flex justify-end">
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
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2.5">
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
                    <select
                      value={groupPeriodType}
                      onChange={(e) => setGroupPeriodType(e.target.value)}
                      className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                      title="Tipo de periodo del grupo"
                    >
                      <option value="">
                        Heredar ({getPeriodMeta(selectedCareerForNewGroup?.effective_period_type ?? orgPeriodType).label})
                      </option>
                      {ACADEMIC_PERIOD_OPTIONS.map((opt) => (
                        <option key={opt.value} value={opt.value}>
                          {opt.label}
                        </option>
                      ))}
                    </select>
                    <input
                      type="text"
                      value={groupSemester}
                      onChange={(e) => setGroupSemester(e.target.value)}
                      placeholder={newGroupPeriodMeta.placeholder}
                      title={newGroupPeriodMeta.singular}
                      className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                    />
                    <input
                      type="text"
                      value={groupDefaultClassroom}
                      onChange={(e) => setGroupDefaultClassroom(e.target.value)}
                      placeholder="Aula fija (ej. Aula 33)"
                      className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                    />
                  </div>
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[11px] text-slate-400">
                      Periodo aplicable: <strong>{newGroupPeriodMeta.singular}</strong> ({newGroupPeriodMeta.label})
                    </span>
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
                    const careerGroups = groups
                      .filter((g) => g.career_id === career.id)
                      .sort((a, b) => comparePeriodsNatural(a.semester, b.semester));
                    const cMeta = getPeriodMeta(career.effective_period_type);
                    return (
                      <div
                        key={career.id}
                        className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-3"
                      >
                        <div className="flex flex-wrap items-start justify-between gap-4">
                          <div>
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="px-2 py-0.5 rounded bg-indigo-500/20 text-indigo-300 text-xs font-semibold">
                                {career.code}
                              </span>
                              <h4 className="text-base font-bold">{career.name}</h4>
                              <span className="px-2 py-0.5 rounded bg-slate-800 border border-slate-700 text-[11px] text-slate-300">
                                {cMeta.label}
                                {career.period_type ? "" : " (heredado)"}
                              </span>
                            </div>
                            {career.description && (
                              <p className="text-xs text-slate-400 mt-1">{career.description}</p>
                            )}
                          </div>
                          <div className="flex items-center gap-2">
                            <select
                              value={career.period_type ?? ""}
                              onChange={(e) =>
                                requestCareerPeriodChange(career, e.target.value)
                              }
                              className="bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-1 text-xs"
                              title="Tipo de periodo de esta carrera (requiere contraseña de administrador)"
                            >
                              <option value="">Usar general ({getPeriodMeta(organization.academic_period_type).label})</option>
                              {ACADEMIC_PERIOD_OPTIONS.map((opt) => (
                                <option key={opt.value} value={opt.value}>
                                  {opt.label}
                                </option>
                              ))}
                            </select>
                            <button
                              type="button"
                              onClick={() => void handleDeleteCareer(career.id)}
                              className="p-1.5 rounded-lg text-slate-400 hover:text-red-400 hover:bg-red-500/10"
                              title="Eliminar carrera"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          </div>
                        </div>

                        {careerGroups.length === 0 ? (
                          <p className="text-xs text-slate-500 italic">
                            Sin grupos vinculados todavía.
                          </p>
                        ) : (
                          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                            {careerGroups.map((g) => {
                              const gMeta = getPeriodMeta(g.period_type);
                              const formattedPeriod = formatGroupPeriodLabel(g.semester, g.period_type);
                              return (
                                <div
                                  key={g.id}
                                  className="rounded-xl bg-slate-800/60 border border-slate-700/70 p-3.5 space-y-2"
                                >
                                  <div className="flex items-start justify-between gap-2">
                                    <div>
                                      <p className="text-sm font-semibold">
                                        {g.name}{" "}
                                        <span className="text-xs font-normal text-slate-400">
                                          ({g.code})
                                        </span>
                                      </p>
                                      <p className="text-xs text-slate-400 mt-0.5">
                                        {formattedPeriod ? (
                                          <span className="text-indigo-300 font-medium">
                                            {formattedPeriod}
                                            {g.custom_period_type ? " (propio)" : ""} ·{" "}
                                          </span>
                                        ) : (
                                          <span>
                                            {gMeta.label}
                                            {g.custom_period_type ? " (propio)" : ""} ·{" "}
                                          </span>
                                        )}
                                        {g.default_classroom ? `${g.default_classroom} · ` : ""}
                                        {g.members_count} alumnos · {g.courses_count} materias
                                      </p>
                                    </div>
                                    <div className="flex items-center gap-1">
                                      <button
                                        type="button"
                                        onClick={() =>
                                          editingGroupId === g.id
                                            ? setEditingGroupId(null)
                                            : startEditGroup(g)
                                        }
                                        className="p-1 text-slate-500 hover:text-indigo-300"
                                        title="Editar periodo, tipo de periodo y aula fija"
                                      >
                                        <Pencil className="w-3.5 h-3.5" />
                                      </button>
                                      <button
                                        type="button"
                                        onClick={() => void handleDeleteGroup(g.id)}
                                        className="p-1 text-slate-500 hover:text-red-400"
                                        title="Eliminar grupo"
                                      >
                                        <Trash2 className="w-3.5 h-3.5" />
                                      </button>
                                    </div>
                                  </div>

                                  {editingGroupId === g.id && (
                                    <div className="grid grid-cols-2 gap-1.5 pt-2 border-t border-slate-700/60">
                                      <select
                                        value={editGroupPeriodType}
                                        onChange={(e) => setEditGroupPeriodType(e.target.value)}
                                        className="col-span-2 bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs"
                                        title="Cambiar tipo de periodo requiere contraseña de administrador"
                                      >
                                        <option value="">Heredar de carrera/institución</option>
                                        {ACADEMIC_PERIOD_OPTIONS.map((opt) => (
                                          <option key={opt.value} value={opt.value}>
                                            {opt.label}
                                          </option>
                                        ))}
                                      </select>
                                      <input
                                        type="text"
                                        value={editGroupSemester}
                                        onChange={(e) => setEditGroupSemester(e.target.value)}
                                        placeholder={`Núm. (${getPeriodMeta(editGroupPeriodType || g.period_type).prefix} ...)`}
                                        className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs"
                                      />
                                      <input
                                        type="text"
                                        value={editGroupClassroom}
                                        onChange={(e) => setEditGroupClassroom(e.target.value)}
                                        placeholder="Aula fija (ej. Aula 33)"
                                        className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs"
                                      />
                                      <button
                                        type="button"
                                        onClick={() => void handleSaveGroupEdit(g)}
                                        className="col-span-2 py-1 rounded bg-indigo-600 hover:bg-indigo-500 text-xs font-semibold"
                                      >
                                        {editGroupPeriodType !== (g.custom_period_type ?? "")
                                          ? "Continuar (requiere clave admin)"
                                          : "Guardar cambios"}
                                      </button>
                                    </div>
                                  )}
                                </div>
                              );
                            })}
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
                        .map((g) => {
                          const gMeta = getPeriodMeta(g.period_type);
                          const formattedPeriod = formatGroupPeriodLabel(g.semester, g.period_type);
                          return (
                            <div
                              key={g.id}
                              className="rounded-xl bg-slate-800/50 border border-slate-700/60 p-3 space-y-2"
                            >
                              <div className="flex flex-wrap items-center justify-between gap-2">
                                <div>
                                  <p className="text-sm font-medium">
                                    {g.name} <span className="text-xs text-slate-400">({g.code})</span>
                                  </p>
                                  <p className="text-xs text-slate-400">
                                    {formattedPeriod ? (
                                      <span className="text-indigo-300 font-medium">
                                        {formattedPeriod} ·{" "}
                                      </span>
                                    ) : (
                                      <span>{gMeta.label} · </span>
                                    )}
                                    {g.default_classroom ? `${g.default_classroom} · ` : ""}
                                    {g.members_count} alumnos · {g.courses_count} materias
                                  </p>
                                </div>
                                <div className="flex items-center gap-1.5">
                                  <button
                                    type="button"
                                    onClick={() =>
                                      editingGroupId === g.id
                                        ? setEditingGroupId(null)
                                        : startEditGroup(g)
                                    }
                                    className="p-1 text-slate-500 hover:text-indigo-300"
                                    title="Editar periodo, tipo de periodo y aula fija"
                                  >
                                    <Pencil className="w-3.5 h-3.5" />
                                  </button>
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
                              </div>

                              {editingGroupId === g.id && (
                                <div className="grid grid-cols-2 gap-1.5 pt-2 border-t border-slate-700/60">
                                  <select
                                    value={editGroupPeriodType}
                                    onChange={(e) => setEditGroupPeriodType(e.target.value)}
                                    className="col-span-2 bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs"
                                  >
                                    <option value="">Heredar de carrera/institución</option>
                                    {ACADEMIC_PERIOD_OPTIONS.map((opt) => (
                                      <option key={opt.value} value={opt.value}>
                                        {opt.label}
                                      </option>
                                    ))}
                                  </select>
                                  <input
                                    type="text"
                                    value={editGroupSemester}
                                    onChange={(e) => setEditGroupSemester(e.target.value)}
                                    placeholder={`Núm. (${getPeriodMeta(editGroupPeriodType || g.period_type).prefix} ...)`}
                                    className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs"
                                  />
                                  <input
                                    type="text"
                                    value={editGroupClassroom}
                                    onChange={(e) => setEditGroupClassroom(e.target.value)}
                                    placeholder="Aula fija (ej. Aula 33)"
                                    className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs"
                                  />
                                  <button
                                    type="button"
                                    onClick={() => void handleSaveGroupEdit(g)}
                                    className="col-span-2 py-1 rounded bg-indigo-600 hover:bg-indigo-500 text-xs font-semibold"
                                  >
                                    {editGroupPeriodType !== (g.custom_period_type ?? "")
                                      ? "Continuar (requiere clave admin)"
                                      : "Guardar cambios"}
                                  </button>
                                </div>
                              )}
                            </div>
                          );
                        })}
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

                  <div className="space-y-2 max-h-64 overflow-y-auto">
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

                {/* Vincular Grupo + Materia + Profesor + Múltiples Días */}
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
                        onChange={(e) => handleSelectCourseGroup(e.target.value)}
                        className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                      >
                        <option value="">Selecciona grupo...</option>
                        {groups.map((g) => (
                          <option key={g.id} value={g.id}>
                            {g.name} ({g.code})
                            {g.default_classroom ? ` · ${g.default_classroom}` : ""}
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
                      <label className="block text-[11px] text-slate-400 mb-1">
                        Clave de periodo / ciclo
                      </label>
                      <input
                        type="text"
                        value={courseTerm}
                        onChange={(e) => setCourseTerm(e.target.value)}
                        placeholder="Ej. 2026-3"
                        className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                      />
                    </div>
                  </div>

                  <div className="pt-2 border-t border-slate-800 space-y-2.5">
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-xs font-semibold text-slate-300">
                        Días y horario de clase (marca uno o varios días)
                      </p>
                      <span className="text-[11px] text-slate-400">
                        {selectedDays.length} día{selectedDays.length === 1 ? "" : "s"}
                      </span>
                    </div>

                    <div className="flex flex-wrap gap-1.5">
                      {WEEKDAYS.map((d) => {
                        const active = selectedDays.includes(d.value);
                        return (
                          <button
                            key={d.value}
                            type="button"
                            onClick={() => toggleSelectedDay(d.value)}
                            className={`px-2.5 py-1 rounded-lg text-xs font-medium border transition-colors ${
                              active
                                ? "bg-indigo-600 border-indigo-500 text-white"
                                : "bg-slate-800 border-slate-700 text-slate-300 hover:bg-slate-700"
                            }`}
                          >
                            {d.short}
                          </button>
                        );
                      })}
                    </div>

                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 items-end">
                      <div>
                        <label className="block text-[10px] text-slate-400 mb-1">Inicio</label>
                        <input
                          type="time"
                          value={initStart}
                          onChange={(e) => setInitStart(e.target.value)}
                          className="w-full bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-2 text-xs"
                        />
                      </div>
                      <div>
                        <label className="block text-[10px] text-slate-400 mb-1">Fin</label>
                        <input
                          type="time"
                          value={initEnd}
                          onChange={(e) => setInitEnd(e.target.value)}
                          className="w-full bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-2 text-xs"
                        />
                      </div>
                      <div>
                        <label className="block text-[10px] text-slate-400 mb-1">
                          Aula (editable)
                        </label>
                        <input
                          type="text"
                          value={initClassroom}
                          onChange={(e) => setInitClassroom(e.target.value)}
                          placeholder="Aula / Lab"
                          className="w-full bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-2 text-xs"
                        />
                      </div>
                      <button
                        type="button"
                        disabled={selectedDays.length === 0}
                        onClick={appendSelectedDaysToPending}
                        className="inline-flex items-center justify-center gap-1.5 px-3.5 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 border border-emerald-400/50 text-white shadow-md shadow-emerald-950/50 ring-1 ring-emerald-400/30 disabled:opacity-40 disabled:shadow-none text-xs font-semibold transition-all"
                        title="Añade estos días para combinar con otros horarios o aulas distintas"
                      >
                        <Plus className="w-3.5 h-3.5 shrink-0" />
                        Agregar horario(s)
                      </button>
                    </div>

                    {pendingSchedules.length > 0 && (
                      <div className="space-y-1.5 rounded-xl bg-slate-800/40 border border-slate-800 p-2.5">
                        <p className="text-[11px] text-slate-400">
                          Horarios acumulados para esta materia ({pendingSchedules.length}):
                        </p>
                        <div className="flex flex-wrap gap-1.5">
                          {pendingSchedules.map((sl, idx) => (
                            <span
                              key={`${sl.day_of_week}-${sl.start_time}-${idx}`}
                              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-indigo-500/15 border border-indigo-500/30 text-[11px] text-indigo-200"
                            >
                              <strong>{dayLabel(sl.day_of_week)}</strong> {sl.start_time}–
                              {sl.end_time}
                              {sl.classroom ? ` · ${sl.classroom}` : ""}
                              <button
                                type="button"
                                onClick={() =>
                                  setPendingSchedules((prev) => prev.filter((_, i) => i !== idx))
                                }
                                className="text-indigo-300 hover:text-white"
                              >
                                <X className="w-3 h-3" />
                              </button>
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
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
                      const draft = getCourseScheduleDraft(course);
                      const inlineClassroom =
                        draft.classroom ?? course.group_default_classroom ?? "";
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
                                {course.career_name ? ` · ${course.career_name}` : ""}
                                {course.semester
                                  ? ` · ${formatGroupPeriodLabel(course.semester, course.period_type)}`
                                  : ""}
                                {course.group_default_classroom
                                  ? ` · Aula base: ${course.group_default_classroom}`
                                  : ""}{" "}
                                · {course.students_count} alumnos heredados
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

                            <div className="pt-1.5 space-y-1.5 border-t border-slate-800/70">
                              <div className="flex flex-wrap gap-1">
                                {WEEKDAYS.map((d) => {
                                  const checked = draft.days.includes(d.value);
                                  return (
                                    <button
                                      key={d.value}
                                      type="button"
                                      onClick={() => toggleInlineDraftDay(course, d.value)}
                                      className={`px-2 py-0.5 rounded text-[11px] font-medium border ${
                                        checked
                                          ? "bg-indigo-600 border-indigo-500 text-white"
                                          : "bg-slate-800 border-slate-700 text-slate-400 hover:text-slate-200"
                                      }`}
                                      title={d.label}
                                    >
                                      {d.mini}
                                    </button>
                                  );
                                })}
                              </div>
                              <div className="grid grid-cols-4 gap-1.5">
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
                                <input
                                  type="text"
                                  value={inlineClassroom}
                                  onChange={(e) =>
                                    setScheduleDrafts((prev) => ({
                                      ...prev,
                                      [course.id]: { ...draft, classroom: e.target.value },
                                    }))
                                  }
                                  placeholder="Aula"
                                  className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-[11px]"
                                />
                                <button
                                  type="button"
                                  onClick={() => void handleAddSchedulesToCourse(course)}
                                  className="inline-flex items-center justify-center gap-1 rounded bg-emerald-600 hover:bg-emerald-500 border border-emerald-400/40 text-white text-[11px] font-semibold px-2 py-1 shadow-sm"
                                >
                                  <Plus className="w-3 h-3" />
                                  Hora(s)
                                </button>
                              </div>
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
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <h3 className="font-semibold text-base">Asistencia por Asignatura</h3>
                      <div className="flex items-center gap-2 text-xs">
                        <span className="text-slate-400">Ordenar por:</span>
                        <select
                          value={subjectSortBy}
                          onChange={(e) => setSubjectSortBy(e.target.value as SubjectSortField)}
                          className="bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-1 text-xs"
                        >
                          <option value="career_period">Carrera y Periodo</option>
                          <option value="period_career">Periodo y Carrera</option>
                          <option value="rate">% Asistencia</option>
                          <option value="subject">Asignatura</option>
                        </select>
                        <button
                          type="button"
                          onClick={() => setSubjectSortAsc((v) => !v)}
                          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-slate-800 border border-slate-700 hover:bg-slate-700 text-xs"
                        >
                          <ArrowUpDown className="w-3.5 h-3.5" />
                          {subjectSortAsc ? "Asc" : "Desc"}
                        </button>
                      </div>
                    </div>

                    <div className="overflow-x-auto">
                      <table className="w-full text-sm text-left">
                        <thead className="text-xs text-slate-400 border-b border-slate-800">
                          <tr>
                            <th className="py-2 pr-3">Carrera</th>
                            <th className="py-2 pr-3">Periodo</th>
                            <th className="py-2 pr-3">Grupo</th>
                            <th className="py-2 pr-3">Materia</th>
                            <th className="py-2 pr-3">Profesor</th>
                            <th className="py-2 pr-3">Sesiones</th>
                            <th className="py-2 pr-3">Asistencias</th>
                            <th className="py-2 pr-3">Retardos</th>
                            <th className="py-2 pr-3">Faltas</th>
                            <th className="py-2 pr-3">% Asistencia</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-800/80">
                          {sortedBySubject.map((row) => (
                            <tr key={row.course_assignment_id}>
                              <td className="py-2.5 pr-3 text-xs text-slate-300">
                                {row.career_name ?? "—"}
                              </td>
                              <td className="py-2.5 pr-3 text-xs text-slate-300">
                                {formatGroupPeriodLabel(row.semester, row.period_type) ??
                                  getPeriodMeta(row.period_type).label}
                              </td>
                              <td className="py-2.5 pr-3 text-xs font-medium">{row.group_name}</td>
                              <td className="py-2.5 pr-3">
                                <span className="font-medium">{row.subject_name}</span>{" "}
                                <span className="text-xs text-slate-400">({row.subject_code})</span>
                              </td>
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
                          {sortedBySubject.length === 0 && (
                            <tr>
                              <td colSpan={10} className="py-6 text-center text-xs text-slate-500">
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
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <h3 className="font-semibold text-base">
                        Consolidado por Grupo (todas sus materias)
                      </h3>
                      <div className="flex items-center gap-2 text-xs">
                        <span className="text-slate-400">Ordenar por:</span>
                        <select
                          value={groupSortBy}
                          onChange={(e) => setGroupSortBy(e.target.value as GroupSortField)}
                          className="bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-1 text-xs"
                        >
                          <option value="career_period">Carrera y Periodo</option>
                          <option value="period_career">Periodo y Carrera</option>
                          <option value="rate">% Asistencia</option>
                          <option value="group">Grupo</option>
                        </select>
                        <button
                          type="button"
                          onClick={() => setGroupSortAsc((v) => !v)}
                          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-slate-800 border border-slate-700 hover:bg-slate-700 text-xs"
                        >
                          <ArrowUpDown className="w-3.5 h-3.5" />
                          {groupSortAsc ? "Asc" : "Desc"}
                        </button>
                      </div>
                    </div>

                    <div className="space-y-3">
                      {sortedByGroup.map((grp) => {
                        const expanded = Boolean(expandedGroupIds[grp.group_id]);
                        const gMeta = getPeriodMeta(grp.period_type);
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
                                  {grp.career_name ?? "Sin carrera"} ·{" "}
                                  {formatGroupPeriodLabel(grp.semester, grp.period_type) ??
                                    `${gMeta.label} (sin núm.)`}{" "}
                                  · {grp.subjects_count} materias · {grp.students_count} alumnos ·{" "}
                                  {grp.total_sessions} sesiones
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

      {pendingPeriodChange && (
        <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4">
          <form
            onSubmit={handleConfirmPeriodChange}
            className="w-full max-w-md bg-slate-900 border border-amber-500/40 rounded-2xl p-6 space-y-4 shadow-2xl"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-2.5">
                <div className="w-9 h-9 rounded-xl bg-amber-500/15 border border-amber-500/30 flex items-center justify-center text-amber-400 shrink-0">
                  <Lock className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="font-bold text-base">Autorización de Administrador</h3>
                  <p className="text-xs text-slate-400">
                    Cambiar el tipo de periodo académico requiere contraseña de administrador.
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => {
                  setPendingPeriodChange(null);
                  setPeriodAuthSecret("");
                  setPeriodAuthError(null);
                }}
                className="text-slate-400 hover:text-white"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="rounded-xl bg-slate-800/70 border border-slate-700 px-3.5 py-2.5 text-xs text-slate-200">
              {pendingPeriodChange.summary}
            </div>

            <div>
              <label className="block text-xs text-slate-400 mb-1">
                Contraseña de administrador
              </label>
              <PasswordInput
                required
                autoFocus
                value={periodAuthSecret}
                onChange={(e) => setPeriodAuthSecret(e.target.value)}
                placeholder="Ingresa la contraseña de administrador"
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-500"
              />
            </div>

            {periodAuthError && (
              <p className="text-xs text-red-300 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2">
                {periodAuthError}
              </p>
            )}

            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => {
                  setPendingPeriodChange(null);
                  setPeriodAuthSecret("");
                  setPeriodAuthError(null);
                }}
                className="px-4 py-2 rounded-lg text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-200"
              >
                Cancelar
              </button>
              <button
                type="submit"
                disabled={periodAuthSubmitting || !periodAuthSecret.trim()}
                className="px-4 py-2 rounded-lg text-xs font-semibold bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white"
              >
                {periodAuthSubmitting ? "Validando..." : "Confirmar cambio"}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
