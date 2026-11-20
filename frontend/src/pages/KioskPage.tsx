import { useCallback, useEffect, useRef, useState } from "react";
import { Pause, Play, Volume2, VolumeX } from "lucide-react";
import { CameraView, type CameraViewHandle } from "../components/CameraView";
import { api } from "../lib/api";
import type {
  ActionMode,
  AttendanceEvent,
  AttendanceSession,
  AuthUser,
  Group,
  Organization,
  RecognizeFrameResponse,
} from "../types/api";

interface KioskPageProps {
  currentUser: AuthUser;
  organization: Organization;
  groups: Group[];
  sessions: AttendanceSession[];
  events: AttendanceEvent[];
  initialSessionId?: number | null;
  onRefreshEvents: () => Promise<void>;
}

function playSuccessBeep() {
  try {
    const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    if (!AudioCtx) return;
    const ctx = new AudioCtx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.setValueAtTime(880, ctx.currentTime);
    gain.gain.setValueAtTime(0.06, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.16);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.16);
  } catch {
    // Silencio si el navegador bloquea AudioContext
  }
}

export function KioskPage({
  currentUser,
  organization,
  groups,
  sessions,
  events,
  initialSessionId,
  onRefreshEvents,
}: KioskPageProps) {
  const cameraRef = useRef<CameraViewHandle | null>(null);
  const inFlightRef = useRef(false);
  const isTeacher = currentUser.role === "teacher";

  const [cameraReady, setCameraReady] = useState(false);
  const [kioskActive, setKioskActive] = useState(true);
  const [soundEnabled, setSoundEnabled] = useState(true);

  const [selectedSessionId, setSelectedSessionId] = useState<string>(
    initialSessionId ? String(initialSessionId) : ""
  );
  const [selectedGroupId, setSelectedGroupId] = useState<string>("");
  const [actionMode, setActionMode] = useState<ActionMode>(
    organization.mode === "education" ? "present" : "auto"
  );

  const [lastResult, setLastResult] = useState<RecognizeFrameResponse | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const openSessions = sessions.filter((s) => s.status === "open");
  const selectedSession =
    openSessions.find((s) => String(s.id) === selectedSessionId) ?? null;

  useEffect(() => {
    setActionMode(organization.mode === "education" ? "present" : "auto");
    setSelectedSessionId(initialSessionId ? String(initialSessionId) : "");
    setSelectedGroupId("");
    setLastResult(null);
  }, [organization.id, organization.mode]);

  useEffect(() => {
    if (initialSessionId) {
      setSelectedSessionId(String(initialSessionId));
      setErrorMsg(null);
    }
  }, [initialSessionId]);

  useEffect(() => {
    if (isTeacher && !selectedSessionId && openSessions.length > 0) {
      setSelectedSessionId(String(openSessions[0].id));
    }
  }, [isTeacher, openSessions, selectedSessionId]);

  const runRecognitionStep = useCallback(async () => {
    if (!kioskActive || !cameraReady || inFlightRef.current) return;
    if (isTeacher && !selectedSessionId) return;
    const cam = cameraRef.current;
    if (!cam) return;

    inFlightRef.current = true;
    try {
      const blob = await cam.captureBlob();
      if (!blob) return;

      const result = await api.recognizeFrame({
        imageBlob: blob,
        organizationId: organization.id,
        sessionId: selectedSessionId ? Number(selectedSessionId) : null,
        groupId: !selectedSessionId && selectedGroupId ? Number(selectedGroupId) : null,
        actionMode,
      });
      setLastResult(result);
      setErrorMsg(null);

      if (result.attendance_action === "recorded") {
        if (soundEnabled) playSuccessBeep();
        await onRefreshEvents();
      }
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Error de conexión con la API.");
    } finally {
      inFlightRef.current = false;
    }
  }, [
    actionMode,
    cameraReady,
    isTeacher,
    kioskActive,
    onRefreshEvents,
    organization.id,
    selectedGroupId,
    selectedSessionId,
    soundEnabled,
  ]);

  useEffect(() => {
    if (!kioskActive || !cameraReady) return;
    const timer = window.setInterval(() => {
      void runRecognitionStep();
    }, 450);
    return () => window.clearInterval(timer);
  }, [cameraReady, kioskActive, runRecognitionStep]);

  let boxStatus: "idle" | "ok" | "warning" | "error" = "idle";
  let boxLabel: string | undefined;

  if (lastResult?.face_box) {
    if (lastResult.match_status === "matched") {
      boxStatus = lastResult.attendance_action === "recorded" ? "ok" : "warning";
      boxLabel = `${lastResult.person?.full_name ?? "Identificado"} · ${(lastResult.confidence * 100).toFixed(0)}%`;
    } else if (lastResult.match_status === "unknown") {
      boxStatus = "error";
      boxLabel = "No reconocido";
    } else {
      boxStatus = "warning";
      if (lastResult.match_status === "ambiguous") {
        boxLabel = "Coincidencia ambigua";
      } else if (lastResult.message.includes("borrosa")) {
        boxLabel = "Imagen borrosa";
      } else if (lastResult.message.includes("Acércate")) {
        boxLabel = "Acércate más";
      } else if (lastResult.message.includes("Contraluz")) {
        boxLabel = "Contraluz fuerte";
      } else if (lastResult.message.includes("iluminación")) {
        boxLabel = "Poca luz";
      } else {
        boxLabel = "Calidad baja";
      }
    }
  }

  return (
    <div className="max-w-6xl mx-auto space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Kiosco Biométrico en Vivo</h2>
          <p className="text-sm text-slate-400">
            Detección y reconocimiento individual en tiempo real (YuNet + SFace ONNX)
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setSoundEnabled((s) => !s)}
            className="p-2.5 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200"
            title={soundEnabled ? "Silenciar aviso" : "Activar aviso sonoro"}
          >
            {soundEnabled ? <Volume2 className="w-4 h-4" /> : <VolumeX className="w-4 h-4" />}
          </button>

          <button
            type="button"
            onClick={() => setKioskActive((v) => !v)}
            className={`inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold transition-colors ${
              kioskActive
                ? "bg-amber-600 hover:bg-amber-500 text-white"
                : "bg-emerald-600 hover:bg-emerald-500 text-white"
            }`}
          >
            {kioskActive ? (
              <>
                <Pause className="w-4 h-4" />
                Pausar Kiosco
              </>
            ) : (
              <>
                <Play className="w-4 h-4" />
                Reanudar Kiosco
              </>
            )}
          </button>
        </div>
      </div>

      {/* Controles de sesión y modo */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 bg-slate-900 border border-slate-800 rounded-2xl p-4">
        <div>
          <label className="block text-xs text-slate-400 mb-1">Sesión activa</label>
          <select
            value={selectedSessionId}
            onChange={(e) => setSelectedSessionId(e.target.value)}
            className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
          >
            {!isTeacher && <option value="">Automática del día</option>}
            {isTeacher && openSessions.length === 0 && (
              <option value="">Sin sesiones abiertas</option>
            )}
            {openSessions.map((s) => (
              <option key={s.id} value={s.id}>
                {s.title}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-xs text-slate-400 mb-1">Alcance por grupo</label>
          <select
            value={selectedGroupId}
            disabled={isTeacher || Boolean(selectedSessionId)}
            onChange={(e) => setSelectedGroupId(e.target.value)}
            className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm disabled:opacity-50"
          >
            <option value="">Toda la organización</option>
            {groups.map((g) => (
              <option key={g.id} value={g.id}>
                {g.name} ({g.code})
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-xs text-slate-400 mb-1">Tipo de movimiento</label>
          <select
            value={actionMode}
            onChange={(e) => setActionMode(e.target.value as ActionMode)}
            className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
          >
            {organization.mode === "enterprise" ? (
              <>
                <option value="auto">Automático (Entrada ↔ Salida)</option>
                <option value="check_in">Solo Entrada (Check-in)</option>
                <option value="check_out">Solo Salida (Check-out)</option>
              </>
            ) : (
              <>
                <option value="present">Pase de lista (Presente)</option>
                <option value="auto">Automático</option>
              </>
            )}
          </select>
        </div>
      </div>

      {isTeacher && !selectedSession && (
        <div className="rounded-xl bg-amber-500/15 border border-amber-500/40 px-4 py-3 text-sm text-amber-200">
          Para tomar asistencia como docente, primero abre una de tus materias desde{" "}
          <strong>Mi Agenda Docente</strong> (o selecciona una sesión abierta arriba).
        </div>
      )}

      {selectedSession && selectedSession.subject_name && (
        <div className="rounded-xl bg-indigo-500/15 border border-indigo-500/40 px-4 py-2.5 text-xs text-indigo-200 flex flex-wrap items-center gap-3">
          <span>
            Materia: <strong>{selectedSession.subject_name}</strong>
            {selectedSession.subject_code ? ` (${selectedSession.subject_code})` : ""}
          </span>
          {selectedSession.group_name && (
            <span>
              · Grupo: <strong>{selectedSession.group_name}</strong>
            </span>
          )}
          {selectedSession.career_name && <span>· {selectedSession.career_name}</span>}
          {selectedSession.teacher_name && (
            <span>
              · Docente: <strong>{selectedSession.teacher_name}</strong>
            </span>
          )}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        {/* Cámara + banner de respuesta */}
        <div className="lg:col-span-3 space-y-4">
          <CameraView
            ref={cameraRef}
            active={kioskActive}
            faceBox={lastResult?.face_box ?? null}
            boxStatus={boxStatus}
            label={boxLabel}
            onReadyChange={setCameraReady}
            onError={setErrorMsg}
          />

          {errorMsg && (
            <div className="rounded-xl bg-red-500/15 border border-red-500/40 px-4 py-3 text-sm text-red-200">
              {errorMsg}
            </div>
          )}

          {lastResult && (
            <div
              className={`rounded-2xl border p-4 flex items-center justify-between gap-4 ${
                lastResult.attendance_action === "recorded"
                  ? "bg-emerald-500/10 border-emerald-500/40"
                  : lastResult.match_status === "unknown"
                    ? "bg-red-500/10 border-red-500/40"
                    : "bg-slate-900 border-slate-800"
              }`}
            >
              <div className="flex items-center gap-3.5 min-w-0">
                {lastResult.person?.avatar_base64 && (
                  <img
                    src={lastResult.person.avatar_base64}
                    alt={lastResult.person.full_name}
                    className="w-12 h-12 rounded-full object-cover border border-slate-700 shrink-0"
                  />
                )}
                <div className="min-w-0">
                  <p className="font-semibold text-sm truncate">{lastResult.message}</p>
                  <p className="text-xs text-slate-400 mt-0.5">
                    Estado: <span className="text-slate-200">{lastResult.match_status}</span>
                    {lastResult.confidence > 0 && (
                      <> · Similitud: {(lastResult.confidence * 100).toFixed(1)}%</>
                    )}
                    {lastResult.worked_minutes !== null && (
                      <> · Jornada: {lastResult.worked_minutes} min</>
                    )}
                    {lastResult.match_status === "low_quality" && lastResult.quality && (
                      <>
                        {" "}
                        · Nitidez: {lastResult.quality.blur_score} · Brillo:{" "}
                        {lastResult.quality.brightness}
                      </>
                    )}
                  </p>
                  {lastResult.quality?.backlight_detected && (
                    <span className="inline-block mt-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-amber-500/15 text-amber-300 border border-amber-500/30">
                      Contraluz detectado · compensación activa
                    </span>
                  )}
                </div>
              </div>
              <span className="text-xs font-mono text-slate-400 shrink-0">
                {lastResult.latency_ms.toFixed(0)} ms
              </span>
            </div>
          )}
        </div>

        {/* Feed en vivo */}
        <div className="lg:col-span-2 bg-slate-900 border border-slate-800 rounded-2xl p-5 flex flex-col">
          <h3 className="font-semibold text-base mb-1">Registros Recientes</h3>
          <p className="text-xs text-slate-400 mb-4">Actualización automática al confirmar rostro</p>

          <div className="space-y-2.5 overflow-y-auto max-h-[460px] pr-1">
            {events.length === 0 ? (
              <p className="text-sm text-slate-500 py-8 text-center">
                Esperando el primer reconocimiento...
              </p>
            ) : (
              events.slice(0, 15).map((ev) => (
                <div
                  key={ev.id}
                  className="flex items-center justify-between gap-3 p-3 rounded-xl bg-slate-800/50 border border-slate-800"
                >
                  <div className="flex items-center gap-2.5 min-w-0">
                    {ev.person_avatar_base64 ? (
                      <img
                        src={ev.person_avatar_base64}
                        alt={ev.person_name}
                        className="w-9 h-9 rounded-full object-cover border border-slate-700 shrink-0"
                      />
                    ) : (
                      <div className="w-9 h-9 rounded-full bg-indigo-600/20 text-indigo-300 flex items-center justify-center text-xs font-bold shrink-0">
                        {ev.person_name.slice(0, 1).toUpperCase()}
                      </div>
                    )}
                    <div className="min-w-0">
                      <p className="text-sm font-medium truncate">{ev.person_name}</p>
                      <p className="text-[11px] text-slate-400">
                        {ev.event_type === "check_in"
                          ? "Entrada"
                          : ev.event_type === "check_out"
                            ? "Salida"
                            : "Presente"}{" "}
                        ·{" "}
                        {ev.status === "on_time"
                          ? "A tiempo"
                          : ev.status === "late"
                            ? "Retardo"
                            : "Manual"}
                      </p>
                    </div>
                  </div>
                  <span className="text-xs text-slate-400 shrink-0">
                    {new Date(ev.timestamp).toLocaleTimeString([], {
                      hour: "2-digit",
                      minute: "2-digit",
                      second: "2-digit",
                    })}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
