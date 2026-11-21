import type { AcademicPeriodType } from "../types/api";

export interface PeriodMeta {
  value: AcademicPeriodType;
  label: string;
  singular: string;
  plural: string;
  placeholder: string;
}

export const ACADEMIC_PERIOD_OPTIONS: PeriodMeta[] = [
  {
    value: "bimestral",
    label: "Bimestral",
    singular: "Bimestre",
    plural: "Bimestres",
    placeholder: "Ej. 3er Bimestre",
  },
  {
    value: "trimestral",
    label: "Trimestral",
    singular: "Trimestre",
    plural: "Trimestres",
    placeholder: "Ej. 4to Trimestre",
  },
  {
    value: "cuatrimestral",
    label: "Cuatrimestral",
    singular: "Cuatrimestre",
    plural: "Cuatrimestres",
    placeholder: "Ej. 6to Cuatrimestre",
  },
  {
    value: "semestral",
    label: "Semestral",
    singular: "Semestre",
    plural: "Semestres",
    placeholder: "Ej. 5to Semestre",
  },
  {
    value: "ciclo",
    label: "Ciclo anual (año completo)",
    singular: "Ciclo / Grado",
    plural: "Ciclos / Grados",
    placeholder: "Ej. 2do Grado / Ciclo 2026",
  },
];

export function getPeriodMeta(periodType?: string | null): PeriodMeta {
  return (
    ACADEMIC_PERIOD_OPTIONS.find((item) => item.value === periodType) ??
    ACADEMIC_PERIOD_OPTIONS[3]
  );
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
