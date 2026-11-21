/**
 * Catálogo, formateo y ordenamiento natural de periodos académicos en IdentIA.
 *
 * Centraliza los cinco regímenes escolares soportados (`bimestral`, `trimestral`,
 * `cuatrimestral`, `semestral` y `ciclo`) para mantener consistencia visual entre
 * la configuración institucional, carreras, grupos, enrolamiento y estadísticas.
 */
import type { TipoPeriodoAcademico } from "../types/api";

/** Metadatos lingüísticos y ejemplos de captura para un tipo de periodo académico. */
export interface MetadatosPeriodo {
  valor: TipoPeriodoAcademico;
  etiqueta: string;
  singular: string;
  plural: string;
  prefijo: string;
  marcadorEjemplo: string;
}

/** Catálogo oficial de tipos de periodo académico seleccionables. */
export const OPCIONES_PERIODO_ACADEMICO: MetadatosPeriodo[] = [
  {
    valor: "bimestral",
    etiqueta: "Bimestral",
    singular: "Bimestre",
    plural: "Bimestres",
    prefijo: "Bimestre",
    marcadorEjemplo: "Ej. 3 (se mostrará Bimestre 3)",
  },
  {
    valor: "trimestral",
    etiqueta: "Trimestral",
    singular: "Trimestre",
    plural: "Trimestres",
    prefijo: "Trimestre",
    marcadorEjemplo: "Ej. 4 (se mostrará Trimestre 4)",
  },
  {
    valor: "cuatrimestral",
    etiqueta: "Cuatrimestral",
    singular: "Cuatrimestre",
    plural: "Cuatrimestres",
    prefijo: "Cuatrimestre",
    marcadorEjemplo: "Ej. 6 (se mostrará Cuatrimestre 6)",
  },
  {
    valor: "semestral",
    etiqueta: "Semestral",
    singular: "Semestre",
    plural: "Semestres",
    prefijo: "Semestre",
    marcadorEjemplo: "Ej. 5 (se mostrará Semestre 5)",
  },
  {
    valor: "ciclo",
    etiqueta: "Ciclo anual (año completo)",
    singular: "Ciclo / Grado",
    plural: "Ciclos / Grados",
    prefijo: "Ciclo",
    marcadorEjemplo: "Ej. 2026 o 2 (se mostrará Ciclo 2026)",
  },
];

/**
 * Obtiene los metadatos de un periodo académico con respaldo a `"semestral"`.
 */
export function obtenerMetadatosPeriodo(tipoPeriodo?: string | null): MetadatosPeriodo {
  return (
    OPCIONES_PERIODO_ACADEMICO.find((elemento) => elemento.valor === tipoPeriodo) ??
    OPCIONES_PERIODO_ACADEMICO[3]
  );
}

/** Expresión regular para remover palabras redundantes al inicio o final del número de periodo. */
const EXPRESION_PALABRA_PERIODO =
  /^(?:bimestres?|trimestres?|cuatrimestres?|semestres?|ciclos?(?:\s+anual)?|grados?|a[ñn]os?)(?:\s+|(?:\s+de\s+))|\s*(?:bimestres?|trimestres?|cuatrimestres?|semestres?|ciclos?|grados?)$/gi;

/**
 * Antepone el tipo de periodo antes del número o etiqueta capturada en el grupo
 * (p. ej. `"6"` -> `"Cuatrimestre 6"`, `"6to Cuatrimestre"` -> `"Cuatrimestre 6to"`).
 */
export function formatearEtiquetaPeriodoGrupo(
  semestre?: string | null,
  tipoPeriodo?: string | null
): string | null {
  const textoCrudo = (semestre ?? "").trim();
  if (!textoCrudo) return null;
  const metadatos = obtenerMetadatosPeriodo(tipoPeriodo);
  let textoLimpio = textoCrudo;
  for (let paso = 0; paso < 2; paso += 1) {
    textoLimpio = textoLimpio.replace(EXPRESION_PALABRA_PERIODO, "").trim();
  }
  return textoLimpio ? `${metadatos.prefijo} ${textoLimpio}` : metadatos.prefijo;
}

/**
 * Ordena etiquetas de periodos de forma natural en español
 * (ej. `"2do Cuatrimestre"` antes que `"10mo Cuatrimestre"`).
 */
export function compararPeriodosNatural(
  primerValor?: string | null,
  segundoValor?: string | null
): number {
  const valorA = (primerValor ?? "").trim();
  const valorB = (segundoValor ?? "").trim();
  if (!valorA && !valorB) return 0;
  if (!valorA) return 1;
  if (!valorB) return -1;
  return valorA.localeCompare(valorB, "es", { numeric: true, sensitivity: "base" });
}
