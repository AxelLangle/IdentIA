import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  Camera,
  Check,
  Plus,
  Search,
  ShieldAlert,
  Sparkles,
  Trash2,
  UserCheck,
} from "lucide-react";
import { CameraView, type CameraViewHandle } from "../components/CameraView";
import { api } from "../lib/api";
import type {
  EnrollFrameResponse,
  Group,
  Organization,
  Person,
  PersonRole,
  PoseLabel,
} from "../types/api";

interface EnrollmentPageProps {
  organization: Organization;
  groups: Group[];
  persons: Person[];
  onRefreshPersons: () => Promise<void>;
}

const POSES: { key: PoseLabel; title: string; instruction: string }[] = [
  { key: "frontal", title: "1. Frontal", instruction: "Mira directamente al centro de la cámara." },
  { key: "left", title: "2. Izquierda", instruction: "Gira suavemente la cabeza a la izquierda." },
  { key: "right", title: "3. Derecha", instruction: "Gira suavemente la cabeza a la derecha." },
  { key: "up", title: "4. Arriba", instruction: "Levanta ligeramente el mentón mirando al frente." },
  { key: "smile", title: "5. Sonrisa", instruction: "Sonríe de forma natural mirando a la cámara." },
];

export function EnrollmentPage({
  organization,
  groups,
  persons,
  onRefreshPersons,
}: EnrollmentPageProps) {
  const cameraRef = useRef<CameraViewHandle | null>(null);

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
  const [enrollStatus, setEnrollStatus] = useState<EnrollFrameResponse | null>(null);
  const [enrollError, setEnrollError] = useState<string | null>(null);

  const activePerson = persons.find((p) => p.id === activePersonId) ?? null;
  const currentPose = POSES[poseIndex] ?? POSES[0];

  useEffect(() => {
    setRole(organization.mode === "education" ? "student" : "employee");
    setStoreAvatar(organization.store_avatar_by_default);
    setActivePersonId(null);
    setAutoCapture(false);
  }, [organization.id, organization.mode, organization.store_avatar_by_default]);

  const filteredPersons = persons.filter((p) => {
    const q = search.trim().toLowerCase();
    if (!q) return true;
    return p.full_name.toLowerCase().includes(q) || p.external_id.toLowerCase().includes(q);
  });

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
      });
      setExternalId("");
      setFullName("");
      setEmail("");
      setSelectedGroupIds([]);
      setShowCreateForm(false);
      await onRefreshPersons();
      if (created.biometric_consent) {
        setActivePersonId(created.id);
        setPoseIndex(0);
        setEnrollStatus(null);
        setEnrollError(null);
      }
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "No se pudo crear el registro.");
    } finally {
      setCreating(false);
    }
  }

  async function captureCurrentPose() {
    if (!activePerson || !cameraReady || capturing) return;
    const cam = cameraRef.current;
    if (!cam) return;

    setCapturing(true);
    setEnrollError(null);
    try {
      const blob = await cam.captureBlob();
      if (!blob) return;
      const res = await api.enrollFrame(
        activePerson.id,
        blob,
        currentPose.key,
        storeAvatar
      );
      setEnrollStatus(res);
      if (res.accepted) {
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
    } finally {
      setCapturing(false);
    }
  }

  useEffect(() => {
    if (!autoCapture || !activePerson || !cameraReady) return;
    const timer = window.setInterval(() => {
      void captureCurrentPose();
    }, 950);
    return () => window.clearInterval(timer);
  });

  async function handleRevokeBiometrics(person: Person) {
    if (!window.confirm(`¿Revocar y eliminar los vectores biométricos de ${person.full_name}?`)) {
      return;
    }
    await api.revokeBiometrics(person.id);
    if (activePersonId === person.id) {
      setEnrollStatus(null);
    }
    await onRefreshPersons();
  }

  async function handleDeletePerson(person: Person) {
    if (!window.confirm(`¿Eliminar permanentemente a ${person.full_name}?`)) return;
    await api.deletePerson(person.id);
    if (activePersonId === person.id) {
      setActivePersonId(null);
      setAutoCapture(false);
    }
    await onRefreshPersons();
  }

  function toggleGroupSelection(gid: number) {
    setSelectedGroupIds((prev) =>
      prev.includes(gid) ? prev.filter((id) => id !== gid) : [...prev, gid]
    );
  }

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Personas y Registro Biométrico</h2>
          <p className="text-sm text-slate-400">
            Alta de padrón y asistente guiado de 5 poses en memoria (sin guardar fotos crudas)
          </p>
        </div>

        <button
          type="button"
          onClick={() => setShowCreateForm((v) => !v)}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold bg-indigo-600 hover:bg-indigo-500 text-white"
        >
          <Plus className="w-4 h-4" />
          Nueva Persona
        </button>
      </div>

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
            <div>
              <p className="text-xs text-slate-400 mb-2">Asignar a grupos / departamentos</p>
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
                    </button>
                  );
                })}
              </div>
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
        <div className="lg:col-span-6 bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4">
          <div className="relative">
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Buscar por nombre o matrícula/ID..."
              className="w-full bg-slate-800 border border-slate-700 rounded-lg pl-9 pr-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          <div className="space-y-2.5 max-h-[540px] overflow-y-auto pr-1">
            {filteredPersons.length === 0 ? (
              <p className="text-sm text-slate-500 py-10 text-center">
                No hay personas registradas que coincidan con la búsqueda.
              </p>
            ) : (
              filteredPersons.map((p) => {
                const isSelected = activePersonId === p.id;
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
                          </p>
                        </div>
                      </div>

                      <span
                        className={`px-2.5 py-1 rounded-full text-xs font-medium shrink-0 ${
                          p.embeddings_count >= 3
                            ? "bg-emerald-500/15 text-emerald-300"
                            : p.embeddings_count > 0
                              ? "bg-amber-500/15 text-amber-300"
                              : "bg-slate-800 text-slate-400"
                        }`}
                      >
                        {p.embeddings_count}/5 poses
                      </span>
                    </div>

                    <div className="flex flex-wrap items-center justify-between gap-2 mt-3 pt-2.5 border-t border-slate-800/80">
                      <div className="text-[11px] text-slate-400">
                        {!p.biometric_consent ? (
                          <span className="text-amber-400">Sin consentimiento biométrico</span>
                        ) : p.needs_reenroll ? (
                          <span className="text-amber-300">Requiere re-enrolamiento</span>
                        ) : (
                          <span>Listo para captura</span>
                        )}
                      </div>

                      <div className="flex items-center gap-1.5">
                        <button
                          type="button"
                          disabled={!p.biometric_consent}
                          onClick={() => {
                            setActivePersonId(p.id);
                            setAutoCapture(false);
                            setEnrollStatus(null);
                            setEnrollError(null);
                            const nextMissing = POSES.findIndex(
                              (pose) => !p.poses_completed.includes(pose.key)
                            );
                            setPoseIndex(nextMissing === -1 ? 0 : nextMissing);
                          }}
                          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white"
                        >
                          <Camera className="w-3.5 h-3.5" />
                          Enrolar
                        </button>

                        {p.embeddings_count > 0 && (
                          <button
                            type="button"
                            onClick={() => void handleRevokeBiometrics(p)}
                            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium bg-slate-800 hover:bg-amber-600/20 text-amber-300 border border-slate-700"
                            title="Revocar biometría"
                          >
                            <ShieldAlert className="w-3.5 h-3.5" />
                            Revocar
                          </button>
                        )}

                        <button
                          type="button"
                          onClick={() => void handleDeletePerson(p)}
                          className="p-1.5 rounded-md text-slate-400 hover:text-red-400 hover:bg-red-500/10"
                          title="Eliminar persona"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Asistente guiado de 5 poses */}
        <div className="lg:col-span-6 bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4">
          {!activePerson ? (
            <div className="h-full min-h-[380px] flex flex-col items-center justify-center text-center text-slate-400 p-6">
              <UserCheck className="w-12 h-12 text-indigo-400/70 mb-3" />
              <h3 className="font-semibold text-base text-slate-200">
                Selecciona una persona para enrolar
              </h3>
              <p className="text-xs text-slate-500 max-w-sm mt-1">
                Solo necesitamos entre 3 y 5 tomas limpias con distintas poses para generar los
                embeddings SFace. No volverás a entrenar modelos pesados.
              </p>
            </div>
          ) : (
            <>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h3 className="font-semibold text-base">{activePerson.full_name}</h3>
                  <p className="text-xs text-slate-400">
                    {activePerson.embeddings_count}/5 poses registradas
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

              {/* Pills de poses */}
              <div className="grid grid-cols-5 gap-1.5">
                {POSES.map((pose, idx) => {
                  const completed = activePerson.poses_completed.includes(pose.key);
                  const selected = idx === poseIndex;
                  return (
                    <button
                      key={pose.key}
                      type="button"
                      onClick={() => setPoseIndex(idx)}
                      className={`px-2 py-2 rounded-lg text-[11px] font-medium border flex items-center justify-center gap-1 transition-colors ${
                        selected
                          ? "bg-indigo-600 border-indigo-400 text-white"
                          : completed
                            ? "bg-emerald-500/15 border-emerald-500/40 text-emerald-300"
                            : "bg-slate-800 border-slate-700 text-slate-400"
                      }`}
                    >
                      {completed && <Check className="w-3 h-3 shrink-0" />}
                      <span className="truncate">{pose.title.split(" ")[1]}</span>
                    </button>
                  );
                })}
              </div>

              <div className="rounded-xl bg-indigo-500/10 border border-indigo-500/30 px-3.5 py-2.5 text-xs text-indigo-200">
                <strong>{currentPose.title}:</strong> {currentPose.instruction}
              </div>

              <CameraView
                ref={cameraRef}
                active={Boolean(activePerson)}
                faceBox={enrollStatus?.face_box ?? null}
                boxStatus={enrollStatus ? (enrollStatus.accepted ? "ok" : "warning") : "idle"}
                label={enrollStatus?.quality ? `Nitidez ${enrollStatus.quality.blur_score}` : undefined}
                onReadyChange={setCameraReady}
                onError={setEnrollError}
              />

              <div className="flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  disabled={!cameraReady || capturing}
                  onClick={() => void captureCurrentPose()}
                  className="flex-1 inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-semibold bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white"
                >
                  <Camera className="w-4 h-4" />
                  {capturing ? "Procesando..." : `Capturar ${currentPose.title}`}
                </button>

                <button
                  type="button"
                  disabled={!cameraReady}
                  onClick={() => setAutoCapture((v) => !v)}
                  className={`inline-flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-semibold border transition-colors ${
                    autoCapture
                      ? "bg-amber-600 border-amber-500 text-white"
                      : "bg-slate-800 border-slate-700 text-slate-200 hover:bg-slate-700"
                  }`}
                >
                  <Sparkles className="w-4 h-4" />
                  {autoCapture ? "Detener Auto" : "Auto-captura"}
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
                    enrollStatus.accepted
                      ? "bg-emerald-500/10 border-emerald-500/40 text-emerald-200"
                      : "bg-amber-500/10 border-amber-500/40 text-amber-200"
                  }`}
                >
                  <p className="font-medium">{enrollStatus.message}</p>
                  {enrollStatus.quality && (
                    <p className="text-[11px] opacity-80 mt-0.5">
                      Nitidez: {enrollStatus.quality.blur_score} · Brillo:{" "}
                      {enrollStatus.quality.brightness} · Tamaño:{" "}
                      {enrollStatus.quality.face_width}×{enrollStatus.quality.face_height}px
                    </p>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
