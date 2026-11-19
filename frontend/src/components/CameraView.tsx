import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { CameraOff } from "lucide-react";
import type { FaceBox } from "../types/api";

export interface CameraViewHandle {
  captureBlob: () => Promise<Blob | null>;
}

interface CameraViewProps {
  active: boolean;
  faceBox?: FaceBox | null;
  boxStatus?: "idle" | "ok" | "warning" | "error";
  label?: string;
  mirrored?: boolean;
  onReadyChange?: (ready: boolean) => void;
  onError?: (message: string) => void;
}

const BOX_COLORS: Record<NonNullable<CameraViewProps["boxStatus"]>, string> = {
  idle: "#818cf8",
  ok: "#10b981",
  warning: "#f59e0b",
  error: "#ef4444",
};

export const CameraView = forwardRef<CameraViewHandle, CameraViewProps>(
  (
    {
      active,
      faceBox = null,
      boxStatus = "idle",
      label,
      mirrored = true,
      onReadyChange,
      onError,
    },
    ref
  ) => {
    const videoRef = useRef<HTMLVideoElement | null>(null);
    const overlayRef = useRef<HTMLCanvasElement | null>(null);
    const captureCanvasRef = useRef<HTMLCanvasElement | null>(null);
    const [cameraReady, setCameraReady] = useState(false);
    const [cameraError, setCameraError] = useState<string | null>(null);

    useImperativeHandle(ref, () => ({
      captureBlob: () =>
        new Promise<Blob | null>((resolve) => {
          const video = videoRef.current;
          if (!video || video.readyState < 2 || video.videoWidth === 0) {
            resolve(null);
            return;
          }
          if (!captureCanvasRef.current) {
            captureCanvasRef.current = document.createElement("canvas");
          }
          const canvas = captureCanvasRef.current;
          canvas.width = video.videoWidth;
          canvas.height = video.videoHeight;
          const ctx = canvas.getContext("2d");
          if (!ctx) {
            resolve(null);
            return;
          }
          ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
          canvas.toBlob((blob) => resolve(blob), "image/jpeg", 0.9);
        }),
    }));

    useEffect(() => {
      if (!active) {
        setCameraReady(false);
        onReadyChange?.(false);
        return;
      }

      let cancelled = false;
      let stream: MediaStream | null = null;

      async function startCamera() {
        setCameraError(null);
        if (!navigator.mediaDevices?.getUserMedia) {
          const msg = "Tu navegador no soporta acceso a cámara WebRTC.";
          setCameraError(msg);
          onError?.(msg);
          return;
        }
        try {
          stream = await navigator.mediaDevices.getUserMedia({
            video: {
              width: { ideal: 640 },
              height: { ideal: 480 },
              facingMode: "user",
            },
            audio: false,
          });
          if (cancelled) {
            stream.getTracks().forEach((t) => t.stop());
            return;
          }
          const video = videoRef.current;
          if (video) {
            video.srcObject = stream;
            await video.play();
            setCameraReady(true);
            onReadyChange?.(true);
          }
        } catch (err) {
          if (cancelled) return;
          const msg =
            err instanceof Error
              ? `No se pudo abrir la cámara: ${err.message}`
              : "No se pudo acceder a la cámara.";
          setCameraError(msg);
          setCameraReady(false);
          onReadyChange?.(false);
          onError?.(msg);
        }
      }

      void startCamera();

      return () => {
        cancelled = true;
        setCameraReady(false);
        onReadyChange?.(false);
        if (stream) {
          stream.getTracks().forEach((track) => track.stop());
        }
        if (videoRef.current) {
          videoRef.current.srcObject = null;
        }
      };
    }, [active, onError, onReadyChange]);

    // Dibuja guía ovalada y bounding box compensando el espejo horizontal
    useEffect(() => {
      const canvas = overlayRef.current;
      if (!canvas) return;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;

      const width = canvas.width;
      const height = canvas.height;
      ctx.clearRect(0, 0, width, height);

      // Guía ovalada central sutil
      ctx.save();
      ctx.strokeStyle = "rgba(148, 163, 184, 0.35)";
      ctx.lineWidth = 2;
      ctx.setLineDash([6, 6]);
      ctx.beginPath();
      ctx.ellipse(width / 2, height / 2, width * 0.19, height * 0.33, 0, 0, Math.PI * 2);
      ctx.stroke();
      ctx.restore();

      if (!faceBox) return;

      const drawW = faceBox.nw * width;
      const drawH = faceBox.nh * height;
      const drawX = mirrored
        ? (1 - faceBox.nx - faceBox.nw) * width
        : faceBox.nx * width;
      const drawY = faceBox.ny * height;

      const color = BOX_COLORS[boxStatus];
      ctx.save();
      ctx.strokeStyle = color;
      ctx.lineWidth = 3;
      ctx.strokeRect(drawX, drawY, drawW, drawH);

      if (label) {
        ctx.font = "600 13px Inter, sans-serif";
        const textWidth = ctx.measureText(label).width;
        const badgeW = textWidth + 16;
        const badgeH = 24;
        const badgeX = Math.max(4, Math.min(width - badgeW - 4, drawX));
        const badgeY = drawY > 30 ? drawY - badgeH - 4 : drawY + drawH + 4;

        ctx.fillStyle = color;
        ctx.fillRect(badgeX, badgeY, badgeW, badgeH);
        ctx.fillStyle = "#ffffff";
        ctx.fillText(label, badgeX + 8, badgeY + 16);
      }
      ctx.restore();
    }, [faceBox, boxStatus, label, mirrored]);

    return (
      <div className="relative w-full aspect-[4/3] bg-slate-900 rounded-2xl overflow-hidden border border-slate-800 shadow-inner">
        <video
          ref={videoRef}
          playsInline
          muted
          className={`w-full h-full object-cover ${mirrored ? "scale-x-[-1]" : ""}`}
        />
        <canvas
          ref={overlayRef}
          width={640}
          height={480}
          className="absolute inset-0 w-full h-full pointer-events-none"
        />

        {(!active || cameraError || !cameraReady) && (
          <div className="absolute inset-0 bg-slate-950/80 backdrop-blur-sm flex flex-col items-center justify-center p-6 text-center">
            <CameraOff className="w-10 h-10 text-slate-400 mb-3" />
            <p className="text-sm text-slate-300 font-medium">
              {cameraError
                ? cameraError
                : active
                  ? "Iniciando cámara WebRTC..."
                  : "Cámara en pausa"}
            </p>
          </div>
        )}
      </div>
    );
  }
);

CameraView.displayName = "CameraView";
