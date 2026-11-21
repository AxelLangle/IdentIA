/**
 * Componente de captura de video en vivo mediante WebRTC (`getUserMedia`) con
 * un lienzo `<canvas>` superpuesto para trazar la guía ovalada de encuadre y el
 * recuadro dinámico del rostro compensando la vista tipo espejo.
 */
import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import { CameraOff } from "lucide-react";
import type { CuadroRostro } from "../types/api";

/**
 * Interfaz imperativa expuesta al componente padre mediante `ref` para capturar
 * fotogramas JPEG bajo demanda sin crear elementos DOM temporales en cada ciclo.
 */
export interface ControlVistaCamara {
  /** Captura el fotograma actual del video como un `Blob` JPEG con orientación real. */
  capturarBlob: () => Promise<Blob | null>;
}

/** Estado semántico visual del recuadro delimitador alrededor del rostro. */
export type EstadoCuadroRostro = "idle" | "ok" | "warning" | "error";

/** Propiedades recibidas por el componente `VistaCamara`. */
interface PropiedadesVistaCamara {
  /** Indica si la transmisión WebRTC debe permanecer encendida. */
  activa: boolean;
  /** Coordenadas del rostro detectado en el último análisis del backend. */
  cuadroRostro?: CuadroRostro | null;
  /** Color de diagnóstico del recuadro (`idle`, `ok`, `warning` o `error`). */
  estadoCuadro?: EstadoCuadroRostro;
  /** Etiqueta de texto breve mostrada encima o debajo del recuadro facial. */
  etiqueta?: string;
  /** Invierte horizontalmente la vista previa y el recuadro (modo espejo). */
  espejada?: boolean;
  /** Callback notificado cuando cambia la disponibilidad del video. */
  alCambiarDisponibilidad?: (lista: boolean) => void;
  /** Callback notificado si ocurre algún error al solicitar o abrir la cámara. */
  alOcurrirError?: (mensaje: string) => void;
}

/** Colores hexadecimales correspondientes a cada estado de validación facial. */
const COLORES_CUADRO: Record<EstadoCuadroRostro, string> = {
  idle: "#818cf8",
  ok: "#10b981",
  warning: "#f59e0b",
  error: "#ef4444",
};

/**
 * Renderiza el flujo de cámara WebRTC (`640x480`, proporción `4:3`) junto con
 * su lienzo de superposición geométrica para enrolamiento y kiosco en vivo.
 */
export const VistaCamara = forwardRef<ControlVistaCamara, PropiedadesVistaCamara>(
  (
    {
      activa,
      cuadroRostro = null,
      estadoCuadro = "idle",
      etiqueta,
      espejada = true,
      alCambiarDisponibilidad,
      alOcurrirError,
    },
    referenciaExterna
  ) => {
    // Referencias DOM al video, superposición visual y lienzo reutilizable de captura.
    const referenciaVideo = useRef<HTMLVideoElement | null>(null);
    const referenciaSuperposicion = useRef<HTMLCanvasElement | null>(null);
    const referenciaLienzoCaptura = useRef<HTMLCanvasElement | null>(null);

    // Estado interno del dispositivo de video.
    const [camaraLista, establecerCamaraLista] = useState(false);
    const [errorCamara, establecerErrorCamara] = useState<string | null>(null);

    // Exponemos el método imperativo de captura reutilizando el mismo lienzo oculto.
    useImperativeHandle(referenciaExterna, () => ({
      capturarBlob: () =>
        new Promise<Blob | null>((resolver) => {
          const elementoVideo = referenciaVideo.current;
          if (!elementoVideo || elementoVideo.readyState < 2 || elementoVideo.videoWidth === 0) {
            resolver(null);
            return;
          }
          if (!referenciaLienzoCaptura.current) {
            referenciaLienzoCaptura.current = document.createElement("canvas");
          }
          const lienzo = referenciaLienzoCaptura.current;
          lienzo.width = elementoVideo.videoWidth;
          lienzo.height = elementoVideo.videoHeight;
          const contexto = lienzo.getContext("2d");
          if (!contexto) {
            resolver(null);
            return;
          }
          // Dibujamos sin inversión horizontal para preservar la geometría real en YuNet/SFace.
          contexto.drawImage(elementoVideo, 0, 0, lienzo.width, lienzo.height);
          lienzo.toBlob((blobGenerado) => resolver(blobGenerado), "image/jpeg", 0.9);
        }),
    }));

    // Ciclo de vida de la cámara WebRTC dependiente del indicador `activa`.
    useEffect(() => {
      if (!activa) {
        establecerCamaraLista(false);
        alCambiarDisponibilidad?.(false);
        return;
      }

      let componenteCancelado = false;
      let flujoVideo: MediaStream | null = null;

      async function iniciarCamara() {
        establecerErrorCamara(null);
        if (!navigator.mediaDevices?.getUserMedia) {
          const mensajeNoSoportado = "Tu navegador no soporta acceso a cámara WebRTC.";
          establecerErrorCamara(mensajeNoSoportado);
          alOcurrirError?.(mensajeNoSoportado);
          return;
        }
        try {
          flujoVideo = await navigator.mediaDevices.getUserMedia({
            video: {
              width: { ideal: 640 },
              height: { ideal: 480 },
              facingMode: "user",
            },
            audio: false,
          });
          if (componenteCancelado) {
            flujoVideo.getTracks().forEach((pista) => pista.stop());
            return;
          }
          const elementoVideo = referenciaVideo.current;
          if (elementoVideo) {
            elementoVideo.srcObject = flujoVideo;
            await elementoVideo.play();
            establecerCamaraLista(true);
            alCambiarDisponibilidad?.(true);
          }
        } catch (errorCaptura) {
          if (componenteCancelado) return;
          const mensajeLegible =
            errorCaptura instanceof Error
              ? `No se pudo abrir la cámara: ${errorCaptura.message}`
              : "No se pudo acceder a la cámara.";
          establecerErrorCamara(mensajeLegible);
          establecerCamaraLista(false);
          alCambiarDisponibilidad?.(false);
          alOcurrirError?.(mensajeLegible);
        }
      }

      void iniciarCamara();

      return () => {
        componenteCancelado = true;
        establecerCamaraLista(false);
        alCambiarDisponibilidad?.(false);
        if (flujoVideo) {
          flujoVideo.getTracks().forEach((pista) => pista.stop());
        }
        if (referenciaVideo.current) {
          referenciaVideo.current.srcObject = null;
        }
      };
    }, [activa, alOcurrirError, alCambiarDisponibilidad]);

    // Dibuja la guía ovalada central y el recuadro delimitador compensando el modo espejo.
    useEffect(() => {
      const lienzo = referenciaSuperposicion.current;
      if (!lienzo) return;
      const contexto = lienzo.getContext("2d");
      if (!contexto) return;

      const ancho = lienzo.width;
      const alto = lienzo.height;
      contexto.clearRect(0, 0, ancho, alto);

      // Guía ovalada central sutil para ayudar a centrar el rostro.
      contexto.save();
      contexto.strokeStyle = "rgba(148, 163, 184, 0.35)";
      contexto.lineWidth = 2;
      contexto.setLineDash([6, 6]);
      contexto.beginPath();
      contexto.ellipse(ancho / 2, alto / 2, ancho * 0.19, alto * 0.33, 0, 0, Math.PI * 2);
      contexto.stroke();
      contexto.restore();

      if (!cuadroRostro) return;

      const anchoDibujo = cuadroRostro.ancho_normalizado * ancho;
      const altoDibujo = cuadroRostro.alto_normalizado * alto;
      const posX = espejada
        ? (1 - cuadroRostro.coordenada_x_normalizada - cuadroRostro.ancho_normalizado) * ancho
        : cuadroRostro.coordenada_x_normalizada * ancho;
      const posY = cuadroRostro.coordenada_y_normalizada * alto;

      const colorTrazo = COLORES_CUADRO[estadoCuadro];
      contexto.save();
      contexto.strokeStyle = colorTrazo;
      contexto.lineWidth = 3;
      contexto.strokeRect(posX, posY, anchoDibujo, altoDibujo);

      if (etiqueta) {
        contexto.font = "600 13px Inter, sans-serif";
        const anchoTexto = contexto.measureText(etiqueta).width;
        const anchoInsignia = anchoTexto + 16;
        const altoInsignia = 24;
        const insigniaX = Math.max(4, Math.min(ancho - anchoInsignia - 4, posX));
        const insigniaY = posY > 30 ? posY - altoInsignia - 4 : posY + altoDibujo + 4;

        contexto.fillStyle = colorTrazo;
        contexto.fillRect(insigniaX, insigniaY, anchoInsignia, altoInsignia);
        contexto.fillStyle = "#ffffff";
        contexto.fillText(etiqueta, insigniaX + 8, insigniaY + 16);
      }
      contexto.restore();
    }, [cuadroRostro, estadoCuadro, etiqueta, espejada]);

    return (
      <div className="relative w-full aspect-[4/3] bg-slate-900 rounded-2xl overflow-hidden border border-slate-800 shadow-inner">
        <video
          ref={referenciaVideo}
          playsInline
          muted
          className={`w-full h-full object-cover ${espejada ? "scale-x-[-1]" : ""}`}
        />
        <canvas
          ref={referenciaSuperposicion}
          width={640}
          height={480}
          className="absolute inset-0 w-full h-full pointer-events-none"
        />

        {(!activa || errorCamara || !camaraLista) && (
          <div className="absolute inset-0 bg-slate-950/80 backdrop-blur-sm flex flex-col items-center justify-center p-6 text-center">
            <CameraOff className="w-10 h-10 text-slate-400 mb-3" />
            <p className="text-sm text-slate-300 font-medium">
              {errorCamara
                ? errorCamara
                : activa
                  ? "Iniciando cámara WebRTC..."
                  : "Cámara en pausa"}
            </p>
          </div>
        )}
      </div>
    );
  }
);

VistaCamara.displayName = "VistaCamara";
