import { defineStore } from 'pinia'

export interface DocumentItem {
  id: string
  nombre: string
  tipo: 'normativa' | 'manual'
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
  vista_manual: Array<Record<string, any>>
  vista_normativa: Array<Record<string, any>>
  motivos_revision: string[]
  total_revision_manual: number
}

export interface ActiveEvidence {
  tipo: 'normativa' | 'manual'
  docId: string
  page: number
  bbox?: [number, number, number, number] // [x1, y1, x2, y2]
  titulo?: string
  texto?: string
}

export const useAppStore = defineStore('app', {
  state: () => ({
    // Autenticación
    isAuthenticated: false,
    authUsername: '',
    authChecking: true,
    authError: null as string | null,

    currentStep: 1,
    // Estado del sistema y proveedores
    serverHealth: null as any,
    providers: [] as any[],
    // Documentos
    normativas: [] as DocumentItem[],
    manuales: [] as DocumentItem[],
    selectedNormativas: [] as string[],
    selectedManuales: [] as string[],
    isTabulating: false,
    tabulateStats: null as any,
    // Índice
    isIndexing: false,
    indexBuilt: false,
    searchResults: [] as SearchResultItem[],
    // Alcance y Configuración de Corrida
    scopePresetNorm: 'Todo el articulado',
    scopeSearchNorm: '',
    scopeModoManual: 'Muestra rápida',
    scopeSampleSize: 5,
    scopeJerarquiaTxt: '',
    dualMode: true,
    minSemanticScore: 0.30,
    faissTopK: 5,
    // Corrida activa
    activeRunId: null as string | null,
    runStatus: null as RunStatus | null,
    isComparing: false,
    progressLabel: '',
    progressPct: 0,
    // Visor de Evidencia (PDF y Chunks)
    activePdf: null as ActiveEvidence | null,
    activeChunk: null as any | null,
    showPdfModal: false,
    showChunkDrawer: false,
    filterSoloRevision: false,
  }),

  actions: {
    async checkAuth() {
      this.authChecking = true
      this.authError = null
      try {
        const res = await fetch('/api/auth/me')
        if (res.ok) {
          const data = await res.json()
          this.isAuthenticated = true
          this.authUsername = data.usuario || ''
          await this.fetchDocuments()
        } else {
          this.isAuthenticated = false
          this.authUsername = ''
        }
      } catch (e) {
        this.isAuthenticated = false
      } finally {
        this.authChecking = false
      }
    },

    async login(username: string, password: string): Promise<boolean> {
      this.authError = null
      try {
        const res = await fetch('/api/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username, password }),
        })
        if (!res.ok) {
          const errData = await res.json().catch(() => ({ detail: 'Error al iniciar sesión' }))
          this.authError = errData.detail || 'Credenciales incorrectas'
          return false
        }
        const data = await res.json()
        this.isAuthenticated = true
        this.authUsername = data.usuario || username
        await this.fetchDocuments()
        return true
      } catch (e: any) {
        this.authError = e.message || 'Error de conexión con el servidor'
        return false
      }
    },

    async logout() {
      try {
        await fetch('/api/auth/logout', { method: 'POST' })
      } catch (e) {
        // ignore
      } finally {
        this.isAuthenticated = false
        this.authUsername = ''
      }
    },

    async fetchHealth() {
      try {
        const res = await fetch('/api/health')
        this.serverHealth = await res.json()
        const pRes = await fetch('/api/config/providers')
        const pData = await pRes.json()
        this.providers = pData.providers || []
      } catch (e) {
        console.error('Error fetching health:', e)
      }
    },

    async fetchDocuments() {
      try {
        const res = await fetch('/api/documents')
        const data = await res.json()
        this.normativas = data.normativas || []
        this.manuales = data.manuales || []
        if (this.selectedNormativas.length === 0 && this.normativas.length > 0) {
          this.selectedNormativas = this.normativas.map(n => n.id)
        }
        if (this.selectedManuales.length === 0 && this.manuales.length > 0) {
          this.selectedManuales = this.manuales.map(m => m.id)
        }
      } catch (e) {
        console.error('Error fetching documents:', e)
      }
    },

    async tabulate() {
      if (this.selectedNormativas.length === 0 || this.selectedManuales.length === 0) return
      this.isTabulating = true
      try {
        const res = await fetch('/api/documents/tabular', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            normativas: this.selectedNormativas,
            manuales: this.selectedManuales,
            do_ocr: false,
          }),
        })
        if (!res.ok) throw new Error(await res.text())
        this.tabulateStats = await res.json()
        this.currentStep = 2
      } catch (e: any) {
        alert('Error al tabular documentos: ' + e.message)
      } finally {
        this.isTabulating = false
      }
    },

    async buildIndex() {
      this.isIndexing = true
      try {
        const res = await fetch('/api/index/build', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ use_chunking: true, max_tokens: 512, solape: 50 }),
        })
        if (!res.ok) throw new Error(await res.text())
        this.indexBuilt = true
        this.currentStep = 3
      } catch (e: any) {
        alert('Error al construir índice: ' + e.message)
      } finally {
        this.isIndexing = false
      }
    },

    async searchTest(query: string) {
      if (!query.trim()) return
      try {
        const res = await fetch('/api/index/search', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query, top_k: 3, min_score: 0.20, use_reranker: true }),
        })
        if (!res.ok) throw new Error(await res.text())
        const data = await res.json()
        this.searchResults = data.results || []
      } catch (e) {
        console.error('Error in search test:', e)
      }
    },

    async startCompare() {
      this.isComparing = true
      this.progressPct = 0
      this.progressLabel = 'Iniciando análisis...'

      const payload = {
        dual_mode: this.dualMode,
        min_score: this.minSemanticScore,
        top_k: this.faissTopK,
        scope: {
          doc_ids_normativa: this.selectedNormativas,
          preset_articulos: this.scopePresetNorm,
          muestra_n: this.scopeModoManual === 'Muestra rápida' ? this.scopeSampleSize : undefined,
          muestra_aleatoria: false,
        },
      }

      try {
        const res = await fetch('/api/compare/start', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        })
        if (!res.ok) throw new Error(await res.text())
        const data = await res.json()
        this.activeRunId = data.run_id
        this.listenToProgress(data.run_id)
        this.currentStep = 4
      } catch (e: any) {
        alert('Error al iniciar comparación: ' + e.message)
        this.isComparing = false
      }
    },

    listenToProgress(runId: string) {
      const evtSource = new EventSource(`/api/compare/stream/${runId}`)

      evtSource.onmessage = async (event) => {
        try {
          const data = JSON.parse(event.data)
          this.progressPct = Math.min(100, Math.round(data.porcentaje * 100))
          this.progressLabel = data.etiqueta || `Procesando (${data.progreso}/${data.total})`

          if (['completado', 'fallido', 'cancelado'].includes(data.estado)) {
            evtSource.close()
            this.isComparing = false
            await this.fetchRunResults(runId)
          }
        } catch (e) {
          console.error('Error parsing SSE event:', e)
        }
      }

      evtSource.onerror = () => {
        evtSource.close()
        this.isComparing = false
        this.fetchRunResults(runId)
      }
    },

    async fetchRunResults(runId: string) {
      try {
        const res = await fetch(`/api/compare/runs/${runId}`)
        if (!res.ok) throw new Error(await res.text())
        this.runStatus = await res.json()
      } catch (e) {
        console.error('Error fetching run results:', e)
      }
    },

    openPdfViewer(tipo: 'normativa' | 'manual', docId: string, page = 1, bbox?: [number, number, number, number], titulo?: string) {
      this.activePdf = { tipo, docId, page, bbox, titulo }
      this.showPdfModal = true
    },

    openChunkInspector(chunkData: any) {
      this.activeChunk = chunkData
      this.showChunkDrawer = true
    },
  },
})
