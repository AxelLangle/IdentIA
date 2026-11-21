import type { AcademicPeriodType } from "../types/api";

export interface PeriodMeta {
  value: AcademicPeriodType;
  label: string;
  singular: string;
  plural: string;
  prefix: string;
  placeholder: string;
}

export const ACADEMIC_PERIOD_OPTIONS: PeriodMeta[] = [
  {
    value: "bimestral",
    label: "Bimestral",
    singular: "Bimestre",
    plural: "Bimestres",
    prefix: "Bimestre",
    placeholder: "Ej. 3 (se mostrará Bimestre 3)",
  },
  {
    value: "trimestral",
    label: "Trimestral",
    singular: "Trimestre",
    plural: "Trimestres",
    prefix: "Trimestre",
    placeholder: "Ej. 4 (se mostrará Trimestre 4)",
  },
  {
    value: "cuatrimestral",
    label: "Cuatrimestral",
    singular: "Cuatrimestre",
    plural: "Cuatrimestres",
    prefix: "Cuatrimestre",
    placeholder: "Ej. 6 (se mostrará Cuatrimestre 6)",
  },
  {
    value: "semestral",
    label: "Semestral",
    singular: "Semestre",
    plural: "Semestres",
    prefix: "Semestre",
    placeholder: "Ej. 5 (se mostrará Semestre 5)",
  },
  {
    value: "ciclo",
    label: "Ciclo anual (año completo)",
    singular: "Ciclo / Grado",
    plural: "Ciclos / Grados",
    prefix: "Ciclo",
    placeholder: "Ej. 2026 o 2 (se mostrará Ciclo 2026)",
  },
];

export function getPeriodMeta(periodType?: string | null): PeriodMeta {
  return (
    ACADEMIC_PERIOD_OPTIONS.find((item) => item.value === periodType) ??
    ACADEMIC_PERIOD_OPTIONS[3]
  );
}

const PERIOD_WORD_EDGE_RE =
  /^(?:bimestres?|trimestres?|cuatrimestres?|semestres?|ciclos?(?:\s+anual)?|grados?|a[ñn]os?)(?:\s+|(?:\s+de\s+))|\s*(?:bimestres?|trimestres?|cuatrimestres?|semestres?|ciclos?|grados?)$/gi;

/**
 * Antepone el tipo de periodo antes del número/etiqueta del grupo
 * (p. ej. "6" -> "Cuatrimestre 6", "6to Cuatrimestre" -> "Cuatrimestre 6to").
 */
export function formatGroupPeriodLabel(
  semester?: string | null,
  periodType?: string | null
): string | null {
  const raw = (semester ?? "").trim();
  if (!raw) return null;
  const meta = getPeriodMeta(periodType);
  let cleaned = raw;
  for (let i = 0; i < 2; i += 1) {
    cleaned = cleaned.replace(PERIOD_WORD_EDGE_RE, "").trim();
  }
  return cleaned ? `${meta.prefix} ${cleaned}` : meta.prefix;
}

/** Ordena nombres de periodos de forma natural ("2do Cuatrimestre" antes de "10mo Cuatrimestre"). */
export function comparePeriodsNatural(a?: string | null, b?: string | null): number {
  const va = (a ?? "").trim();
  const vb = (b ?? "").trim();
  if (!va && !vb) return 0;
  if (!va) return 1;
  if (!vb) return -1;
  return va.localeCompare(vb, "es", { numeric: true, sensitivity: "base" });
}
