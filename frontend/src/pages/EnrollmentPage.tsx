import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import {
  AlertTriangle,
  Camera,
  Check,
  CheckCircle2,
  KeyRound,
  Plus,
  RotateCcw,
  Search,
  ShieldAlert,
  Sparkles,
  Trash2,
  UserCheck,
  X,
} from "lucide-react";
import { CameraView, type CameraViewHandle } from "../components/CameraView";
import { PasswordInput } from "../components/PasswordInput";
import {
  comparePeriodsNatural,
  formatGroupPeriodLabel,
  getPeriodMeta,
} from "../lib/academicPeriods";
import { api } from "../lib/api";
import type {
  AuthUser,
  CourseAssignment,
  EnrollFrameResponse,
  Group,
  Organization,
  Person,
  PersonRole,
  PoseLabel,
  WorkShift,
} from "../types/api";

interface EnrollmentPageProps {
  currentUser: AuthUser;
  organization: Organization;
  groups: Group[];
  persons: Person[];
  onRefreshPersons: () => Promise<void>;
}

const POSES: { key: PoseLabel; title: string; shortLabel: string; instruction: string }[] = [
  {
    key: "frontal",
    title: "1. Frontal",
    shortLabel: "Frontal",
    instruction: "Mira directamente al centro de la cámara con rostro nivelado.",
  },
  {
    key: "left",
    title: "2. Izquierda",
    shortLabel: "Izquierda",
    instruction: "Gira suavemente la cabeza hacia tu izquierda manteniendo los ojos visibles.",
  },
  {
    key: "right",
    title: "3. Derecha",
    shortLabel: "Derecha",
    instruction: "Gira suavemente la cabeza hacia tu derecha manteniendo los ojos visibles.",
  },
  {
    key: "up",
    title: "4. Arriba",
    shortLabel: "Arriba",
    instruction: "Levanta ligeramente el mentón mirando un poco hacia arriba.",
  },
  {
    key: "down",
    title: "5. Abajo",
    shortLabel: "Abajo",
    instruction: "Inclina suavemente la cabeza mirando ligeramente hacia abajo.",
  },
  {
    key: "smile",
    title: "6. Sonrisa",
    shortLabel: "Sonrisa",
    instruction: "Mira al frente y sonríe de forma marcada y natural.",
  },
];

const TOTAL_POSES = POSES.length;

export function EnrollmentPage({
  currentUser,
  organization,
  groups,
  persons,
  onRefreshPersons,
}: EnrollmentPageProps) {
  const cameraRef = useRef<CameraViewHandle | null>(null);
  const inFlightRef = useRef(false);
  const pauseUntilRef = useRef(0);
  const stabilityRef = useRef(0);
  const previewsRef = useRef<Partial<Record<PoseLabel, string>>>({});

  const [search, setSearch] = useState("");
  const [showCreateForm, setShowCreateForm] = useState(false);

  // Formulario alta
  const [externalId, setExternalId] = useState("");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<PersonRole>(
    organization.mode === "education" ? "student" : "employee"
  );
  const [selectedGroupIds, setSelectedGroupIds] = useState<number[]>([]);
  const [biometricConsent, setBiometricConsent] = useState(true);
  const [formError, setFormError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  // Asistente de enrolamiento
  const [activePersonId, setActivePersonId] = useState<number | null>(null);
  const [poseIndex, setPoseIndex] = useState(0);
  const [storeAvatar, setStoreAvatar] = useState(organization.store_avatar_by_default);
  const [cameraReady, setCameraReady] = useState(false);
  const [capturing, setCapturing] = useState(false);
  const [autoCapture, setAutoCapture] = useState(false);
  const [stabilityCount, setStabilityCount] = useState(0);
  const [enrollStatus, setEnrollStatus] = useState<EnrollFrameResponse | null>(null);
  const [enrollError, setEnrollError] = useState<string | null>(null);
  const [posePreviews, setPosePreviews] = useState<Partial<Record<PoseLabel, string>>>({});
  const [completedBanner, setCompletedBanner] = useState<string | null>(null);

  // Revocación segura (individual o en lote)
  const [selectedForRevoke, setSelectedForRevoke] = useState<number[]>([]);
  const [revokeTargets, setRevokeTargets] = useState<Person[] | null>(null);
  const [revokeSecret, setRevokeSecret] = useState("");
  const [revokeReason, setRevokeReason] = useState("");
  const [revokeError, setRevokeError] = useState<string | null>(null);
  const [revoking, setRevoking] = useState(false);

  // Materias heredadas y filtros por grupo/carrera/periodo (modo educación) y turnos (empresa)
  const [courses, setCourses] = useState<CourseAssignment[]>([]);
  const [workShifts, setWorkShifts] = useState<WorkShift[]>([]);
  const [selectedWorkShiftId, setSelectedWorkShiftId] = useState<string>("");
  const [formCareerFilter, setFormCareerFilter] = useState<string>("");
  const [listGroupFilter, setListGroupFilter] = useState<string>("");
  const [listShiftFilter, setListShiftFilter] = useState<string>("");

  const canManagePersons = ["superadmin", "org_admin", "supervisor", "operator"].includes(
    currentUser.role
  );
  const canDeletePersons = ["superadmin", "org_admin"].includes(currentUser.role);

  const activePerson = persons.find((p) => p.id === activePersonId) ?? null;
  const currentPose = POSES[poseIndex] ?? POSES[0];

  const revokeAllPreviews = useCallback(() => {
    Object.values(previewsRef.current).forEach((url) => {
      if (url) URL.revokeObjectURL(url);
    });
    previewsRef.current = {};
    setPosePreviews({});
  }, []);

  useEffect(() => {
    return () => {
      revokeAllPreviews();
    };
  }, [revokeAllPreviews]);

  useEffect(() => {
    if (organization.mode !== "education" || currentUser.role === "teacher") {
      setCourses([]);
      return;
    }
    let cancelled = false;
    api
      .listCourses(organization.id)
      .then((list) => {
        if (!cancelled) setCourses(list);
      })
      .catch(() => {
        if (!cancelled) setCourses([]);
      });
    return () => {
      cancelled = true;
    };
  }, [currentUser.role, organization.id, organization.mode]);

  useEffect(() => {
    if (organization.mode !== "enterprise") {
      setWorkShifts([]);
      return;
    }
    let cancelled = false;
    api
      .listWorkShifts(organization.id)
      .then((list) => {
        if (!cancelled) setWorkShifts(list);
      })
      .catch(() => {
        if (!cancelled) setWorkShifts([]);
      });
    return () => {
      cancelled = true;
    };
  }, [organization.id, organization.mode]);

  useEffect(() => {
    setRole(organization.mode === "education" ? "student" : "employee");
    setStoreAvatar(organization.store_avatar_by_default);
    setActivePersonId(null);
    setAutoCapture(false);
    setCompletedBanner(null);
    setSelectedForRevoke([]);
    setRevokeTargets(null);
    setSelectedWorkShiftId("");
    setFormCareerFilter("");
    setListGroupFilter("");
    setListShiftFilter("");
    revokeAllPreviews();
  }, [
    organization.id,
    organization.mode,
    organization.store_avatar_by_default,
    revokeAllPreviews,
  ]);

  const filteredPersons = persons.filter((p) => {
    if (listGroupFilter && !p.group_ids.includes(Number(listGroupFilter))) {
      return false;
    }
    if (organization.mode === "enterprise" && listShiftFilter) {
      if (listShiftFilter === "__none__" && p.effective_work_shift_id !== null) {
        return false;
      }
      if (
        listShiftFilter !== "__none__" &&
        String(p.effective_work_shift_id ?? "") !== listShiftFilter
      ) {
        return false;
      }
    }
    const q = search.trim().toLowerCase();
    if (!q) return true;
    return p.full_name.toLowerCase().includes(q) || p.external_id.toLowerCase().includes(q);
  });

  // Agrupación de grupos académicos por Carrera -> Periodo
  const careerFilterOptions = Array.from(
    new Map(
      groups
        .filter((g) => g.career_id !== null && g.career_name)
        .map((g) => [String(g.career_id), g.career_name!])
    ).entries()
  ).sort((a, b) => a[1].localeCompare(b[1], "es"));

  const groupedAcademicBuckets = (() => {
    const filtered = formCareerFilter
      ? groups.filter((g) =>
          formCareerFilter === "__none__"
            ? g.career_id === null
            : String(g.career_id) === formCareerFilter
        )
      : groups;

    const careerMap = new Map<
      string,
      { careerLabel: string; periodType: string; periods: Map<string, Group[]> }
    >();

    for (const g of filtered) {
      const cKey = g.career_id !== null ? String(g.career_id) : "__none__";
      const cLabel = g.career_name ?? "Sin carrera asignada";
      if (!careerMap.has(cKey)) {
        careerMap.set(cKey, {
          careerLabel: cLabel,
          periodType: g.period_type,
          periods: new Map(),
        });
      }
      const bucket = careerMap.get(cKey)!;
      const pKey = formatGroupPeriodLabel(g.semester, g.period_type) ?? "Sin periodo";
      const list = bucket.periods.get(pKey) ?? [];
      list.push(g);
      bucket.periods.set(pKey, list);
    }

    return Array.from(careerMap.entries())
      .sort(([kA, a], [kB, b]) => {
        if (kA === "__none__") return 1;
        if (kB === "__none__") return -1;
        return a.careerLabel.localeCompare(b.careerLabel, "es");
      })
      .map(([careerKey, bucket]) => ({
        careerKey,
        careerLabel: bucket.careerLabel,
        periodMeta: getPeriodMeta(bucket.periodType),
        periods: Array.from(bucket.periods.entries())
          .sort(([pA], [pB]) => {
            if (pA === "Sin periodo") return 1;
            if (pB === "Sin periodo") return -1;
            return comparePeriodsNatural(pA, pB);
          })
          .map(([periodLabel, periodGroups]) => ({
            periodLabel,
            groups: [...periodGroups].sort((x, y) =>
              x.name.localeCompare(y.name, "es", { numeric: true })
            ),
          })),
      }));
  })();

  function startEnrollmentFor(person: Person) {
    revokeAllPreviews();
    stabilityRef.current = 0;
    setStabilityCount(0);
    setCompletedBanner(null);
    setActivePersonId(person.id);
    setAutoCapture(false);
    setEnrollStatus(null);
    setEnrollError(null);
    const nextMissing = POSES.findIndex((pose) => !person.poses_completed.includes(pose.key));
    setPoseIndex(nextMissing === -1 ? 0 : nextMissing);
  }

  function finishEnrollment() {
    if (!activePerson) return;
    const personName = activePerson.full_name;
    const count = activePerson.poses_completed.length;
    setAutoCapture(false);
    setActivePersonId(null);
    setEnrollStatus(null);
    setEnrollError(null);
    stabilityRef.current = 0;
    setStabilityCount(0);
    revokeAllPreviews();
    setCompletedBanner(
      `Enrolamiento de ${personName} finalizado (${count}/${TOTAL_POSES} poses guardadas en memoria vectorial).`
    );
  }

  async function handleCreatePerson(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    setCreating(true);
    try {
      const created = await api.createPerson({
        organization_id: organization.id,
        external_id: externalId.trim(),
        full_name: fullName.trim(),
        email: email.trim() || null,
        role,
        biometric_consent: biometricConsent,
        group_ids: selectedGroupIds,
        work_shift_id:
          organization.mode === "enterprise" && selectedWorkShiftId
            ? Number(selectedWorkShiftId)
            : null,
      });
      setExternalId("");
      setFullName("");
      setEmail("");
      setSelectedGroupIds([]);
      setSelectedWorkShiftId("");
      setShowCreateForm(false);
      await onRefreshPersons();
      if (created.biometric_consent) {
        startEnrollmentFor(created);
      }
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "No se pudo crear el registro.");
    } finally {
      setCreating(false);
    }
  }

  const saveMemoryPreview = useCallback((poseKey: PoseLabel, blob: Blob) => {
    const prevUrl = previewsRef.current[poseKey];
    if (prevUrl) URL.revokeObjectURL(prevUrl);
    const nextUrl = URL.createObjectURL(blob);
    previewsRef.current = { ...previewsRef.current, [poseKey]: nextUrl };
    setPosePreviews({ ...previewsRef.current });
  }, []);

  const submitCapture = useCallback(
    async (poseKey: PoseLabel, dryRun: boolean) => {
      if (!activePerson || !cameraReady || inFlightRef.current) return;
      const cam = cameraRef.current;
      if (!cam) return;

      inFlightRef.current = true;
      if (!dryRun) setCapturing(true);
      setEnrollError(null);
      try {
        const blob = await cam.captureBlob();
        if (!blob) return;

        const res = await api.enrollFrame(
          activePerson.id,
          blob,
          poseKey,
          storeAvatar,
          dryRun
        );
        setEnrollStatus(res);

        if (dryRun) {
          if (res.pose_valid) {
            stabilityRef.current += 1;
            setStabilityCount(stabilityRef.current);
            if (stabilityRef.current >= 2) {
              stabilityRef.current = 0;
              setStabilityCount(0);
              setCapturing(true);
              const commitRes = await api.enrollFrame(
                activePerson.id,
                blob,
                poseKey,
                storeAvatar,
                false
              );
              setEnrollStatus(commitRes);
              if (commitRes.accepted) {
                saveMemoryPreview(poseKey, blob);
                pauseUntilRef.current = Date.now() + 1100;
                await onRefreshPersons();
                const nextMissingIdx = POSES.findIndex(
                  (p) => !commitRes.poses_completed.includes(p.key)
                );
                if (nextMissingIdx !== -1) {
                  setPoseIndex(nextMissingIdx);
                } else {
                  setAutoCapture(false);
                }
              }
            }
          } else {
            stabilityRef.current = 0;
            setStabilityCount(0);
          }
          return;
        }

        if (res.accepted) {
          saveMemoryPreview(poseKey, blob);
          pauseUntilRef.current = Date.now() + 900;
          await onRefreshPersons();
          const nextMissingIdx = POSES.findIndex(
            (p) => !res.poses_completed.includes(p.key)
          );
          if (nextMissingIdx !== -1) {
            setPoseIndex(nextMissingIdx);
          } else {
            setAutoCapture(false);
          }
        }
      } catch (err) {
        setEnrollError(err instanceof Error ? err.message : "Error al enviar captura.");
        setAutoCapture(false);
        stabilityRef.current = 0;
        setStabilityCount(0);
      } finally {
        inFlightRef.current = false;
        setCapturing(false);
      }
    },
    [activePerson, cameraReady, onRefreshPersons, saveMemoryPreview, storeAvatar]
  );

  useEffect(() => {
    if (!autoCapture || !activePerson || !cameraReady) return;
    const timer = window.setInterval(() => {
      if (Date.now() < pauseUntilRef.current) return;
      void submitCapture(currentPose.key, true);
    }, 450);
    return () => window.clearInterval(timer);
  }, [activePerson, autoCapture, cameraReady, currentPose.key, submitCapture]);

  function openRevokeModal(targets: Person[]) {
    setRevokeTargets(targets);
    setRevokeSecret("");
    setRevokeReason("");
    setRevokeError(null);
  }

  async function handleConfirmRevoke(e: FormEvent) {
    e.preventDefault();
    if (!revokeTargets || revokeTargets.length === 0) return;
    setRevoking(true);
    setRevokeError(null);
    try {
      const targetIds = revokeTargets.map((p) => p.id);
      const res = await api.revokeBiometricsBatch({
        person_ids: targetIds,
        authorization_secret: revokeSecret,
        reason: revokeReason.trim() || undefined,
      });
      if (activePersonId !== null && targetIds.includes(activePersonId)) {
        setEnrollStatus(null);
        revokeAllPreviews();
      }
      setSelectedForRevoke((prev) => prev.filter((id) => !targetIds.includes(id)));
      setRevokeTargets(null);
      await onRefreshPersons();
      setCompletedBanner(
        `Biometría revocada para ${res.revoked_persons_count} persona(s) (${res.deleted_embeddings} vectores eliminados). Autorizado por: ${res.authorized_by_name ?? "Administrador"}.`
      );
    } catch (err) {
      setRevokeError(err instanceof Error ? err.message : "No se pudo autorizar la revocación.");
    } finally {
      setRevoking(false);
    }
  }

  function toggleRevokeSelection(personId: number) {
    setSelectedForRevoke((prev) =>
      prev.includes(personId) ? prev.filter((id) => id !== personId) : [...prev, personId]
    );
  }

  async function handleDeletePerson(person: Person) {
    if (!window.confirm(`¿Eliminar permanentemente a ${person.full_name}?`)) return;
    await api.deletePerson(person.id);
    if (activePersonId === person.id) {
      setActivePersonId(null);
      setAutoCapture(false);
      revokeAllPreviews();
    }
    await onRefreshPersons();
  }

  function toggleGroupSelection(gid: number) {
    setSelectedGroupIds((prev) =>
      prev.includes(gid) ? prev.filter((id) => id !== gid) : [...prev, gid]
    );
  }

  const completedCount = activePerson?.poses_completed.length ?? 0;
  const allPosesDone = completedCount >= TOTAL_POSES;
  const progressPct = Math.round((completedCount / TOTAL_POSES) * 100);

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Personas y Registro Biométrico</h2>
          <p className="text-sm text-slate-400">
            Asistente guiado de {TOTAL_POSES} poses con validación geométrica e iluminación (sin
            guardar fotos crudas)
          </p>
        </div>

        {canManagePersons && (
          <button
            type="button"
            onClick={() => setShowCreateForm((v) => !v)}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold bg-indigo-600 hover:bg-indigo-500 text-white"
          >
            <Plus className="w-4 h-4" />
            Nueva Persona
          </button>
        )}
      </div>

      {completedBanner && (
        <div className="rounded-2xl bg-emerald-500/15 border border-emerald-500/40 px-4 py-3 flex items-center justify-between gap-3 text-sm text-emerald-200">
          <div className="flex items-center gap-2.5">
            <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" />
            <span>{completedBanner}</span>
          </div>
          <button
            type="button"
            onClick={() => setCompletedBanner(null)}
            className="text-xs text-emerald-300 hover:underline shrink-0"
          >
            Ocultar
          </button>
        </div>
      )}

      {showCreateForm && (
        <form
          onSubmit={handleCreatePerson}
          className="bg-slate-900 border border-indigo-500/40 rounded-2xl p-5 space-y-4"
        >
          <h3 className="font-semibold text-base">Registrar Persona</h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <div>
              <label className="block text-xs text-slate-400 mb-1">
                {organization.mode === "education" ? "Matrícula / ID" : "Núm. Empleado / ID"}
              </label>
              <input
                type="text"
                required
                value={externalId}
                onChange={(e) => setExternalId(e.target.value)}
                placeholder="Ej. A-2025-01"
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
              />
            </div>

            <div>
              <label className="block text-xs text-slate-400 mb-1">Nombre completo</label>
              <input
                type="text"
                required
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                placeholder="Nombre y apellidos"
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
              />
            </div>

            <div>
              <label className="block text-xs text-slate-400 mb-1">Correo (opcional)</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="correo@ejemplo.com"
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
              />
            </div>

            <div>
              <label className="block text-xs text-slate-400 mb-1">Rol</label>
              <select
                value={role}
                onChange={(e) => setRole(e.target.value as PersonRole)}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
              >
                <option value="employee">Empleado</option>
                <option value="student">Alumno</option>
                <option value="teacher">Docente</option>
                <option value="admin">Administrador</option>
              </select>
            </div>
          </div>

          {groups.length > 0 && (
            <div className="space-y-2.5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-xs text-slate-400">
                  {organization.mode === "education"
                    ? "Asignar a grupo académico (ordenado por carrera y periodo; heredará sus materias)"
                    : "Asignar a grupos / departamentos"}
                </p>
                {organization.mode === "education" && careerFilterOptions.length > 1 && (
                  <select
                    value={formCareerFilter}
                    onChange={(e) => setFormCareerFilter(e.target.value)}
                    className="bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-1 text-xs"
                  >
                    <option value="">Todas las carreras</option>
                    {careerFilterOptions.map(([id, name]) => (
                      <option key={id} value={id}>
                        {name}
                      </option>
                    ))}
                    {groups.some((g) => g.career_id === null) && (
                      <option value="__none__">Sin carrera asignada</option>
                    )}
                  </select>
                )}
              </div>

              {organization.mode === "education" ? (
                <div className="space-y-3 max-h-60 overflow-y-auto pr-1">
                  {groupedAcademicBuckets.map((careerBucket) => (
                    <div
                      key={careerBucket.careerKey}
                      className="rounded-xl bg-slate-800/40 border border-slate-800 p-3 space-y-2"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-xs font-semibold text-indigo-300">
                          {careerBucket.careerLabel}
                        </p>
                        <span className="text-[10px] text-slate-400">
                          Sistema {careerBucket.periodMeta.label.toLowerCase()}
                        </span>
                      </div>

                      <div className="space-y-2">
                        {careerBucket.periods.map((periodBucket) => (
                          <div key={periodBucket.periodLabel} className="space-y-1">
                            <p className="text-[11px] font-medium text-slate-400">
                              {periodBucket.periodLabel}
                            </p>
                            <div className="flex flex-wrap gap-1.5">
                              {periodBucket.groups.map((g) => {
                                const selected = selectedGroupIds.includes(g.id);
                                return (
                                  <button
                                    key={g.id}
                                    type="button"
                                    onClick={() => toggleGroupSelection(g.id)}
                                    className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
                                      selected
                                        ? "bg-indigo-600 border-indigo-500 text-white"
                                        : "bg-slate-800 border-slate-700 text-slate-300 hover:bg-slate-700"
                                    }`}
                                  >
                                    {g.name}
                                    {g.default_classroom ? ` · ${g.default_classroom}` : ""}
                                  </button>
                                );
                              })}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {groups.map((g) => {
                    const selected = selectedGroupIds.includes(g.id);
                    return (
                      <button
                        key={g.id}
                        type="button"
                        onClick={() => toggleGroupSelection(g.id)}
                        className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
                          selected
                            ? "bg-indigo-600 border-indigo-500 text-white"
                            : "bg-slate-800 border-slate-700 text-slate-300 hover:bg-slate-700"
                        }`}
                      >
                        {g.name}
                        {g.default_work_shift_code ? ` · ${g.default_work_shift_code}` : ""}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {organization.mode === "enterprise" && workShifts.some((s) => s.is_active) && (
            <div className="sm:max-w-sm">
              <label className="block text-xs text-slate-400 mb-1">
                Turno laboral directo (opcional)
              </label>
              <select
                value={selectedWorkShiftId}
                onChange={(e) => setSelectedWorkShiftId(e.target.value)}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
              >
                <option value="">Heredar de departamento / Sin turno</option>
                {workShifts
                  .filter((sh) => sh.is_active)
                  .map((sh) => (
                    <option key={sh.id} value={sh.id}>
                      {sh.name} ({sh.start_time}–{sh.end_time}
                      {sh.crosses_midnight ? " 🌙" : ""})
                    </option>
                  ))}
              </select>
            </div>
          )}

          <label className="flex items-start gap-2.5 text-xs text-slate-300 bg-slate-800/60 border border-slate-700 rounded-xl p-3 cursor-pointer">
            <input
              type="checkbox"
              checked={biometricConsent}
              onChange={(e) => setBiometricConsent(e.target.checked)}
              className="mt-0.5 rounded border-slate-600 bg-slate-800 text-indigo-600"
            />
            <span>
              <strong>Consentimiento biométrico informado:</strong> La persona autoriza generar sus
              vectores matemáticos faciales. Las capturas de cámara se procesan en memoria RAM y no
              se almacenan fotografías crudas en el servidor.
            </span>
          </label>

          {formError && (
            <p className="text-xs text-red-300 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2">
              {formError}
            </p>
          )}

          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setShowCreateForm(false)}
              className="px-4 py-2 rounded-lg text-sm bg-slate-800 hover:bg-slate-700"
            >
              Cancelar
            </button>
            <button
              type="submit"
              disabled={creating}
              className="px-4 py-2 rounded-lg text-sm font-semibold bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50"
            >
              {creating ? "Guardando..." : "Guardar y continuar"}
            </button>
          </div>
        </form>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Lista del padrón */}
        <div className="lg:col-span-5 bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4">
          <div className="flex flex-col sm:flex-row gap-2">
            <div className="relative flex-1">
              <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Buscar por nombre o matrícula/ID..."
                className="w-full bg-slate-800 border border-slate-700 rounded-lg pl-9 pr-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>
            {organization.mode === "education" && groups.length > 0 && (
              <select
                value={listGroupFilter}
                onChange={(e) => setListGroupFilter(e.target.value)}
                className="sm:w-48 bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-2 text-xs"
              >
                <option value="">Todos los grupos</option>
                {groupedAcademicBuckets.map((cb) =>
                  cb.periods.map((pb) => (
                    <optgroup
                      key={`${cb.careerKey}-${pb.periodLabel}`}
                      label={`${cb.careerLabel} — ${pb.periodLabel}`}
                    >
                      {pb.groups.map((g) => (
                        <option key={g.id} value={g.id}>
                          {g.name}
                        </option>
                      ))}
                    </optgroup>
                  ))
                )}
              </select>
            )}
            {organization.mode === "enterprise" && workShifts.length > 0 && (
              <select
                value={listShiftFilter}
                onChange={(e) => setListShiftFilter(e.target.value)}
                className="sm:w-48 bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-2 text-xs"
              >
                <option value="">Todos los turnos</option>
                <option value="__none__">Sin turno asignado</option>
                {workShifts.map((sh) => (
                  <option key={sh.id} value={sh.id}>
                    {sh.name} ({sh.code})
                  </option>
                ))}
              </select>
            )}
          </div>

          {selectedForRevoke.length > 0 && (
            <div className="flex items-center justify-between gap-2 rounded-xl bg-amber-500/10 border border-amber-500/30 px-3 py-2 text-xs">
              <span className="text-amber-200">
                {selectedForRevoke.length} seleccionado(s) con biometría
              </span>
              <button
                type="button"
                onClick={() => {
                  const targets = persons.filter((p) => selectedForRevoke.includes(p.id));
                  if (targets.length > 0) openRevokeModal(targets);
                }}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md font-semibold bg-amber-600 hover:bg-amber-500 text-white"
              >
                <ShieldAlert className="w-3.5 h-3.5" />
                Revocar lote
              </button>
            </div>
          )}

          <div className="space-y-2.5 max-h-[640px] overflow-y-auto pr-1">
            {filteredPersons.length === 0 ? (
              <p className="text-sm text-slate-500 py-10 text-center">
                No hay personas registradas que coincidan con la búsqueda.
              </p>
            ) : (
              filteredPersons.map((p) => {
                const isSelected = activePersonId === p.id;
                const isChecked = selectedForRevoke.includes(p.id);
                const personGroups = groups.filter((g) => p.group_ids.includes(g.id));
                const inheritedCourses =
                  organization.mode === "education"
                    ? courses.filter((c) => p.group_ids.includes(c.group_id))
                    : [];
                return (
                  <div
                    key={p.id}
                    className={`p-3.5 rounded-xl border transition-colors ${
                      isSelected
                        ? "bg-indigo-600/10 border-indigo-500/50"
                        : "bg-slate-800/40 border-slate-800 hover:border-slate-700"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="flex items-center gap-3 min-w-0">
                        {p.embeddings_count > 0 && (
                          <input
                            type="checkbox"
                            checked={isChecked}
                            onChange={() => toggleRevokeSelection(p.id)}
                            className="rounded border-slate-600 bg-slate-800 text-amber-500 shrink-0"
                            title="Seleccionar para revocación en lote"
                          />
                        )}
                        {p.avatar_base64 ? (
                          <img
                            src={p.avatar_base64}
                            alt={p.full_name}
                            className="w-10 h-10 rounded-full object-cover border border-slate-700 shrink-0"
                          />
                        ) : (
                          <div className="w-10 h-10 rounded-full bg-slate-800 flex items-center justify-center text-sm font-bold text-slate-300 shrink-0">
                            {p.full_name.slice(0, 1).toUpperCase()}
                          </div>
                        )}
                        <div className="min-w-0">
                          <p className="font-semibold text-sm truncate">{p.full_name}</p>
                          <p className="text-xs text-slate-400">
                            {p.external_id} · {p.role}
                            {personGroups.length > 0
                              ? ` · ${personGroups
                                  .map(
                                    (g) =>
                                      `${g.name}${
                                        g.semester
                                          ? ` (${formatGroupPeriodLabel(g.semester, g.period_type)})`
                                          : ""
                                      }`
                                  )
                                  .join(", ")}`
                              : ""}
                          </p>
                        </div>
                      </div>

                      <span
                        className={`px-2.5 py-1 rounded-full text-xs font-medium shrink-0 ${
                          p.embeddings_count >= TOTAL_POSES
                            ? "bg-emerald-500/15 text-emerald-300"
                            : p.embeddings_count > 0
                              ? "bg-amber-500/15 text-amber-300"
                              : "bg-slate-800 text-slate-400"
                        }`}
                      >
                        {p.embeddings_count}/{TOTAL_POSES} poses
                      </span>
                    </div>

                    {organization.mode === "enterprise" && p.effective_work_shift_name && (
                      <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px]">
                        <span className="text-slate-400">Turno:</span>
                        <span
                          className={`px-2 py-0.5 rounded border ${
                            p.shift_source === "direct"
                              ? "bg-indigo-500/15 text-indigo-300 border-indigo-500/25"
                              : "bg-emerald-500/15 text-emerald-300 border-emerald-500/25"
                          }`}
                        >
                          {p.effective_work_shift_name}
                          {p.effective_work_shift_code ? ` (${p.effective_work_shift_code})` : ""} ·{" "}
                          {p.shift_source === "direct" ? "directo" : "heredado"}
                        </span>
                      </div>
                    )}

                    {inheritedCourses.length > 0 && (
                      <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px]">
                        <span className="text-slate-400">
                          Hereda {inheritedCourses.length} materia
                          {inheritedCourses.length === 1 ? "" : "s"}:
                        </span>
                        {inheritedCourses.map((c) => (
                          <span
                            key={c.id}
                            className="px-2 py-0.5 rounded bg-indigo-500/15 text-indigo-300 border border-indigo-500/20"
                            title={c.subject_name}
                          >
                            {c.subject_code}
                          </span>
                        ))}
                      </div>
                    )}

                    <div className="flex flex-wrap items-center justify-between gap-2 mt-3 pt-2.5 border-t border-slate-800/80">
                      <div className="text-[11px] text-slate-400">
                        {!p.biometric_consent ? (
                          <span className="text-amber-400">Sin consentimiento biométrico</span>
                        ) : p.needs_reenroll ? (
                          <span className="text-amber-300">
                            Actualiza rostro (nueva normalización)
                          </span>
                        ) : p.embeddings_count >= TOTAL_POSES ? (
                          <span className="text-emerald-300">Registro biométrico completo</span>
                        ) : (
                          <span>Listo para captura</span>
                        )}
                      </div>

                      <div className="flex items-center gap-1.5">
                        {canManagePersons && (
                          <button
                            type="button"
                            disabled={!p.biometric_consent}
                            onClick={() => startEnrollmentFor(p)}
                            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white"
                          >
                            <Camera className="w-3.5 h-3.5" />
                            Enrolar
                          </button>
                        )}

                        {p.embeddings_count > 0 && (
                          <button
                            type="button"
                            onClick={() => openRevokeModal([p])}
                            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium bg-slate-800 hover:bg-amber-600/20 text-amber-300 border border-slate-700"
                            title="Revocar biometría (requiere contraseña)"
                          >
                            <ShieldAlert className="w-3.5 h-3.5" />
                            Revocar
                          </button>
                        )}

                        {canDeletePersons && (
                          <button
                            type="button"
                            onClick={() => void handleDeletePerson(p)}
                            className="p-1.5 rounded-md text-slate-400 hover:text-red-400 hover:bg-red-500/10"
                            title="Eliminar persona"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Asistente guiado de 6 poses */}
        <div className="lg:col-span-7 bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4">
          {!activePerson ? (
            <div className="h-full min-h-[420px] flex flex-col items-center justify-center text-center text-slate-400 p-6">
              <UserCheck className="w-12 h-12 text-indigo-400/70 mb-3" />
              <h3 className="font-semibold text-base text-slate-200">
                Selecciona una persona para enrolar
              </h3>
              <p className="text-xs text-slate-500 max-w-sm mt-1">
                Capturaremos {TOTAL_POSES} poses distintas verificadas en tiempo real para que el
                reconocimiento sea preciso incluso con cambios de ángulo o luz.
              </p>
            </div>
          ) : (
            <>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h3 className="font-semibold text-base">{activePerson.full_name}</h3>
                  <p className="text-xs text-slate-400">
                    Progreso: {completedCount} de {TOTAL_POSES} poses completadas ({progressPct}%)
                  </p>
                </div>

                <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={storeAvatar}
                    onChange={(e) => setStoreAvatar(e.target.checked)}
                    className="rounded border-slate-600 bg-slate-800 text-indigo-600"
                  />
                  Guardar avatar (frontal)
                </label>
              </div>

              {/* Barra de progreso */}
              <div className="w-full h-2 rounded-full bg-slate-800 overflow-hidden">
                <div
                  className={`h-full transition-all duration-300 ${
                    allPosesDone ? "bg-emerald-500" : "bg-indigo-500"
                  }`}
                  style={{ width: `${progressPct}%` }}
                />
              </div>

              {/* Banner destacado cuando se completan las 6 poses */}
              {allPosesDone && (
                <div className="rounded-2xl bg-emerald-500/15 border border-emerald-500/40 p-4 flex flex-wrap items-center justify-between gap-3">
                  <div className="space-y-1">
                    <p className="font-semibold text-sm text-emerald-200 flex items-center gap-2">
                      <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                      ¡Enrolamiento biométrico completado ({TOTAL_POSES}/{TOTAL_POSES})!
                    </p>
                    <p className="text-xs text-emerald-200/80">
                      Los vectores ya están almacenados sin guardar fotos crudas. Puedes repetir
                      cualquier toma abajo o finalizar el registro.
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={finishEnrollment}
                    className="px-4 py-2 rounded-lg text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-white shrink-0"
                  >
                    Finalizar enrolamiento
                  </button>
                </div>
              )}

              {/* Instrucción actual + estabilidad */}
              <div className="rounded-xl bg-indigo-500/10 border border-indigo-500/30 px-3.5 py-2.5 flex items-center justify-between gap-3 text-xs text-indigo-200">
                <div>
                  <strong>{currentPose.title}:</strong> {currentPose.instruction}
                </div>
                {autoCapture && (
                  <span className="px-2 py-0.5 rounded-full bg-indigo-600/40 text-[11px] font-semibold shrink-0">
                    Estabilidad {stabilityCount}/2
                  </span>
                )}
              </div>

              <CameraView
                ref={cameraRef}
                active={Boolean(activePerson)}
                faceBox={enrollStatus?.face_box ?? null}
                boxStatus={
                  enrollStatus
                    ? enrollStatus.accepted || enrollStatus.pose_valid
                      ? "ok"
                      : "warning"
                    : "idle"
                }
                label={
                  enrollStatus?.quality
                    ? enrollStatus.pose_valid
                      ? `Pose OK · ${currentPose.shortLabel}`
                      : `Detectado: ${enrollStatus.quality.pose_hint}`
                    : undefined
                }
                onReadyChange={setCameraReady}
                onError={setEnrollError}
              />

              <div className="flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  disabled={!cameraReady || capturing}
                  onClick={() => void submitCapture(currentPose.key, false)}
                  className="flex-1 inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-semibold bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white"
                >
                  <Camera className="w-4 h-4" />
                  {capturing ? "Procesando..." : `Capturar ${currentPose.title}`}
                </button>

                <button
                  type="button"
                  disabled={!cameraReady}
                  onClick={() => {
                    stabilityRef.current = 0;
                    setStabilityCount(0);
                    setAutoCapture((v) => !v);
                  }}
                  className={`inline-flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-semibold border transition-colors ${
                    autoCapture
                      ? "bg-amber-600 border-amber-500 text-white"
                      : "bg-slate-800 border-slate-700 text-slate-200 hover:bg-slate-700"
                  }`}
                >
                  <Sparkles className="w-4 h-4" />
                  {autoCapture ? "Detener Auto" : "Auto-captura guiada"}
                </button>
              </div>

              {enrollError && (
                <p className="text-xs text-red-300 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2">
                  {enrollError}
                </p>
              )}

              {enrollStatus && (
                <div
                  className={`rounded-xl border px-3.5 py-2.5 text-xs ${
                    enrollStatus.accepted || enrollStatus.pose_valid
                      ? "bg-emerald-500/10 border-emerald-500/40 text-emerald-200"
                      : "bg-amber-500/10 border-amber-500/40 text-amber-200"
                  }`}
                >
                  <div className="flex items-center gap-2 font-medium">
                    {enrollStatus.quality?.backlight_detected && (
                      <AlertTriangle className="w-4 h-4 text-amber-300 shrink-0" />
                    )}
                    <span>{enrollStatus.message}</span>
                  </div>
                  {enrollStatus.quality && (
                    <p className="text-[11px] opacity-80 mt-0.5">
                      Nitidez: {enrollStatus.quality.blur_score} · Brillo:{" "}
                      {enrollStatus.quality.brightness} · Asimetría luz:{" "}
                      {enrollStatus.quality.shadow_asymmetry} · Tamaño:{" "}
                      {enrollStatus.quality.face_width}×{enrollStatus.quality.face_height}px
                    </p>
                  )}
                </div>
              )}

              {/* Revisión temporal de las 6 poses en memoria RAM */}
              <div className="space-y-2 pt-1">
                <p className="text-xs text-slate-400">
                  Revisión de tomas (vista temporal en navegador; pulsa Repetir si deseas rehacer
                  alguna pose):
                </p>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5">
                  {POSES.map((pose, idx) => {
                    const completed = activePerson.poses_completed.includes(pose.key);
                    const selected = idx === poseIndex;
                    const previewUrl = posePreviews[pose.key];
                    return (
                      <div
                        key={pose.key}
                        className={`rounded-xl border p-2.5 flex items-center justify-between gap-2 transition-colors ${
                          selected
                            ? "bg-indigo-600/15 border-indigo-400"
                            : completed
                              ? "bg-emerald-500/10 border-emerald-500/30"
                              : "bg-slate-800/50 border-slate-800"
                        }`}
                      >
                        <button
                          type="button"
                          onClick={() => {
                            stabilityRef.current = 0;
                            setStabilityCount(0);
                            setPoseIndex(idx);
                          }}
                          className="flex items-center gap-2 min-w-0 text-left flex-1"
                        >
                          {previewUrl ? (
                            <img
                              src={previewUrl}
                              alt={pose.shortLabel}
                              className="w-9 h-9 rounded-lg object-cover border border-slate-700 scale-x-[-1] shrink-0"
                            />
                          ) : (
                            <div
                              className={`w-9 h-9 rounded-lg flex items-center justify-center shrink-0 ${
                                completed
                                  ? "bg-emerald-500/20 text-emerald-300"
                                  : "bg-slate-800 text-slate-500"
                              }`}
                            >
                              {completed ? (
                                <Check className="w-4 h-4" />
                              ) : (
                                <span className="text-xs font-semibold">{idx + 1}</span>
                              )}
                            </div>
                          )}
                          <div className="min-w-0">
                            <p className="text-xs font-medium truncate">{pose.shortLabel}</p>
                            <p className="text-[10px] text-slate-400">
                              {completed ? "Lista" : "Pendiente"}
                            </p>
                          </div>
                        </button>

                        {completed && (
                          <button
                            type="button"
                            onClick={() => {
                              stabilityRef.current = 0;
                              setStabilityCount(0);
                              setPoseIndex(idx);
                            }}
                            className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[11px] bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 shrink-0"
                            title={`Repetir ${pose.shortLabel}`}
                          >
                            <RotateCcw className="w-3 h-3" />
                            Repetir
                          </button>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Modal de autorización para revocar registros biométricos */}
      {revokeTargets && (
        <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4">
          <form
            onSubmit={handleConfirmRevoke}
            className="w-full max-w-md bg-slate-900 border border-amber-500/40 rounded-2xl p-6 space-y-4 shadow-2xl"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-2.5">
                <div className="w-9 h-9 rounded-xl bg-amber-500/15 border border-amber-500/30 flex items-center justify-center text-amber-300">
                  <KeyRound className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="font-semibold text-base">Autorizar revocación biométrica</h3>
                  <p className="text-xs text-slate-400">
                    {revokeTargets.length === 1
                      ? revokeTargets[0].full_name
                      : `${revokeTargets.length} personas seleccionadas`}
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setRevokeTargets(null)}
                className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="rounded-xl bg-slate-800/60 border border-slate-800 p-3 text-xs text-slate-300 max-h-28 overflow-y-auto space-y-1">
              {revokeTargets.map((t) => (
                <p key={t.id}>
                  • <strong>{t.full_name}</strong> ({t.external_id})
                </p>
              ))}
            </div>

            <div>
              <label className="block text-xs text-slate-400 mb-1">
                Contraseña de seguridad (Admin, Superadmin o Clave Delegada)
              </label>
              <PasswordInput
                required
                autoFocus
                value={revokeSecret}
                onChange={(e) => setRevokeSecret(e.target.value)}
                placeholder="Ingresa contraseña de autorización"
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-500"
              />
            </div>

            <div>
              <label className="block text-xs text-slate-400 mb-1">Motivo (opcional)</label>
              <input
                type="text"
                value={revokeReason}
                onChange={(e) => setRevokeReason(e.target.value)}
                placeholder="Ej. Re-enrolamiento o baja del padrón"
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
              />
            </div>

            {revokeError && (
              <p className="text-xs text-red-300 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2">
                {revokeError}
              </p>
            )}

            <div className="flex justify-end gap-2 pt-1">
              <button
                type="button"
                onClick={() => setRevokeTargets(null)}
                className="px-4 py-2 rounded-lg text-sm bg-slate-800 hover:bg-slate-700"
              >
                Cancelar
              </button>
              <button
                type="submit"
                disabled={revoking}
                className="px-4 py-2 rounded-lg text-sm font-semibold bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white"
              >
                {revoking ? "Validando..." : "Confirmar revocación"}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
