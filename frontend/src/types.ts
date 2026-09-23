export type TipoDoc = 'normativa' | 'manual'

export interface DocumentItem {
  id: string
  nombre: string
  tipo: TipoDoc
  size_bytes: number
  tiene_pdf: boolean
}

export interface SearchResultItem {
  element_id: string
  numero: string
  encabezado: string
  contenido: string
  score: number
  doc_id: string
}

/** Fila de las vistas Vía 1 / Vía 2 y resultado de búsqueda: el backend las devuelve como dict. */
export type Fila = Record<string, any>

export interface RunStatus {
  run_id: string
  estado: string
  progreso: number
  total: number
  porcentaje: number
  etiqueta: string
  cobertura_global?: number
  alerta_cobertura?: string
  articulos_sin_cobertura: Array<{ doc_id: string; numero: string }>
  articulos_parciales: Array<{ doc_id: string; numero: string }>
  articulos_no_aplican: Array<{ doc_id: string; numero: string }>
  vista_manual: Fila[]
  vista_normativa: Fila[]
  motivos_revision: string[]
  total_revision_manual: number
}

export interface ServerHealth {
  status: string
  version?: string
  device?: string
  platform?: string
}
