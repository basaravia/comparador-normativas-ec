import { create } from 'zustand'
import { ApiError, api, post, urls } from '@/api/client'
import type {
  DocumentItem,
  RunStatus,
  SearchResultItem,
  ServerHealth,
  TipoDoc,
} from '@/types'

const mensaje = (e: unknown) => (e instanceof Error ? e.message : String(e))
const TERMINALES = ['completado', 'fallido', 'cancelado']

interface AppState {
  // Sesión: la UI mínima no tiene login; se apoya en AUTH_ENABLED=false del backend.
  authChecking: boolean
  authBlocked: boolean

  // Navegación y errores visibles
  currentStep: number
  error: string | null

  // Sistema
  serverHealth: ServerHealth | null

  // Documentos
  normativas: DocumentItem[]
  manuales: DocumentItem[]
  selectedNormativas: string[]
  selectedManuales: string[]
  isTabulating: boolean

  // Índice
  isIndexing: boolean
  indexBuilt: boolean
  searchResults: SearchResultItem[]

  // Alcance y configuración de corrida
  scopePresetNorm: string
  scopeSearchNorm: string
  scopeModoManual: string
  scopeSampleSize: number
  scopeJerarquiaTxt: string
  dualMode: boolean
  minSemanticScore: number
  faissTopK: number

  // Corrida activa
  activeRunId: string | null
  runStatus: RunStatus | null
  isComparing: boolean
  progressLabel: string
  progressPct: number
  filterSoloRevision: boolean

  set: (patch: Partial<AppState>) => void
  clearError: () => void
  checkAuth: () => Promise<void>
  fetchHealth: () => Promise<void>
  fetchDocuments: () => Promise<void>
  toggleDoc: (tipo: TipoDoc, id: string) => void
  tabulate: () => Promise<void>
  buildIndex: () => Promise<void>
  searchTest: (query: string) => Promise<void>
  startCompare: () => Promise<void>
  fetchRunResults: (runId: string) => Promise<void>
}

let eventSource: EventSource | null = null

export const useAppStore = create<AppState>((set, get) => ({
  authChecking: true,
  authBlocked: false,

  currentStep: 1,
  error: null,

  serverHealth: null,

  normativas: [],
  manuales: [],
  selectedNormativas: [],
  selectedManuales: [],
  isTabulating: false,

  isIndexing: false,
  indexBuilt: false,
  searchResults: [],

  scopePresetNorm: 'Todo el articulado',
  scopeSearchNorm: '',
  scopeModoManual: 'Muestra rápida',
  scopeSampleSize: 5,
  scopeJerarquiaTxt: '',
  dualMode: true,
  minSemanticScore: 0.3,
  faissTopK: 5,

  activeRunId: null,
  runStatus: null,
  isComparing: false,
  progressLabel: '',
  progressPct: 0,
  filterSoloRevision: false,


  set: (patch) => set(patch),
  clearError: () => set({ error: null }),

  async checkAuth() {
    set({ authChecking: true, authBlocked: false })
    try {
      await api('/api/auth/me')
      await get().fetchDocuments()
    } catch (e) {
      // 401: el backend exige sesión y esta UI no tiene login.
      set({ authBlocked: e instanceof ApiError && e.status === 401 })
      if (!(e instanceof ApiError && e.status === 401)) set({ error: `No se pudo contactar la API: ${mensaje(e)}` })
    } finally {
      set({ authChecking: false })
    }
  },

  async fetchHealth() {
    try {
      set({ serverHealth: await api<ServerHealth>('/api/health') })
    } catch (e) {
      console.error('health:', e)
    }
  },

  async fetchDocuments() {
    try {
      const data = await api<{ normativas?: DocumentItem[]; manuales?: DocumentItem[] }>('/api/documents')
      const normativas = data.normativas ?? []
      const manuales = data.manuales ?? []
      const s = get()
      set({
        normativas,
        manuales,
        selectedNormativas: s.selectedNormativas.length ? s.selectedNormativas : normativas.map((n) => n.id),
        selectedManuales: s.selectedManuales.length ? s.selectedManuales : manuales.map((m) => m.id),
      })
    } catch (e) {
      set({ error: `No se pudieron cargar los documentos: ${mensaje(e)}` })
    }
  },

  toggleDoc(tipo, id) {
    const clave = tipo === 'normativa' ? 'selectedNormativas' : 'selectedManuales'
    const actual = get()[clave]
    set({ [clave]: actual.includes(id) ? actual.filter((x) => x !== id) : [...actual, id] } as Partial<AppState>)
  },

  async tabulate() {
    const { selectedNormativas, selectedManuales } = get()
    if (!selectedNormativas.length || !selectedManuales.length) return
    set({ isTabulating: true, error: null })
    try {
      await post('/api/documents/tabular', {
        normativas: selectedNormativas,
        manuales: selectedManuales,
        do_ocr: false,
      })
      set({ currentStep: 2 })
    } catch (e) {
      set({ error: `Error al tabular documentos: ${mensaje(e)}` })
    } finally {
      set({ isTabulating: false })
    }
  },

  async buildIndex() {
    set({ isIndexing: true, error: null })
    try {
      await post('/api/index/build', { use_chunking: true, max_tokens: 512, solape: 50 })
      set({ indexBuilt: true, currentStep: 3 })
    } catch (e) {
      set({ error: `Error al construir el índice: ${mensaje(e)}` })
    } finally {
      set({ isIndexing: false })
    }
  },

  async searchTest(query) {
    if (!query.trim()) return
    try {
      const data = await post<{ results?: SearchResultItem[] }>('/api/index/search', {
        query,
        top_k: 3,
        min_score: 0.2,
        use_reranker: true,
      })
      set({ searchResults: data.results ?? [] })
    } catch (e) {
      set({ error: `Error en la búsqueda: ${mensaje(e)}` })
    }
  },

  async startCompare() {
    const s = get()
    set({ isComparing: true, progressPct: 0, progressLabel: 'Iniciando análisis...', error: null, runStatus: null })
    try {
      const data = await post<{ run_id: string }>('/api/compare/start', {
        dual_mode: s.dualMode,
        min_score: s.minSemanticScore,
        top_k: s.faissTopK,
        scope: {
          doc_ids_normativa: s.selectedNormativas,
          preset_articulos: s.scopePresetNorm,
          muestra_n: s.scopeModoManual === 'Muestra rápida' ? s.scopeSampleSize : undefined,
          muestra_aleatoria: false,
        },
      })
      set({ activeRunId: data.run_id, currentStep: 4 })
      listenToProgress(data.run_id, set, get)
    } catch (e) {
      set({ error: `Error al iniciar la comparación: ${mensaje(e)}`, isComparing: false })
    }
  },

  async fetchRunResults(runId) {
    try {
      set({ runStatus: await api<RunStatus>(urls.run(runId)) })
    } catch (e) {
      set({ error: `No se pudieron leer los resultados: ${mensaje(e)}` })
    }
  }
}))

function listenToProgress(
  runId: string,
  set: (patch: Partial<AppState>) => void,
  get: () => AppState,
) {
  eventSource?.close()
  const es = new EventSource(urls.stream(runId))
  eventSource = es

  es.onmessage = async (event) => {
    try {
      const data = JSON.parse(event.data)
      set({
        progressPct: Math.min(100, Math.round((data.porcentaje ?? 0) * 100)),
        progressLabel: data.etiqueta || `Procesando (${data.progreso}/${data.total})`,
      })
      if (TERMINALES.includes(data.estado)) {
        es.close()
        set({ isComparing: false })
        await get().fetchRunResults(runId)
      }
    } catch (e) {
      console.error('SSE:', e)
    }
  }

  es.onerror = () => {
    es.close()
    set({ isComparing: false })
    void get().fetchRunResults(runId)
  }
}
