import { useState } from 'react'
import { ArrowRight, Database, Loader2, Search } from 'lucide-react'
import { useAppStore } from '@/store/useAppStore'

export default function Step2Index() {
  const isIndexing = useAppStore((s) => s.isIndexing)
  const indexBuilt = useAppStore((s) => s.indexBuilt)
  const results = useAppStore((s) => s.searchResults)
  const buildIndex = useAppStore((s) => s.buildIndex)
  const searchTest = useAppStore((s) => s.searchTest)
  const set = useAppStore((s) => s.set)
  const [query, setQuery] = useState('política de crédito y evaluación de capacidad de pago')

  return (
    <div className="space-y-6">
      <div className="bg-surface p-5 rounded-xl border border-border shadow-sm flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-base sm:text-lg font-bold text-content-main">🧭 Paso 2: Índice Semántico Vectorial FAISS</h2>
          <p className="text-xs sm:text-sm text-content-muted mt-1">
            Indexa los artículos con el modelo parent-child (Ítem 8) para optimizar el recall de fragmentos largos.
          </p>
        </div>
        <div className="flex items-center space-x-3 w-full sm:w-auto">
          <button
            onClick={() => void buildIndex()}
            disabled={isIndexing}
            className="flex-1 sm:flex-none px-5 py-2.5 rounded-lg bg-primary hover:bg-primary-hover text-white text-xs sm:text-sm font-semibold flex items-center justify-center gap-2 shadow transition disabled:opacity-50"
          >
            {isIndexing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Database className="w-4 h-4" />}
            <span>{isIndexing ? 'Construyendo FAISS…' : indexBuilt ? 'Reconstruir Índice' : 'Construir Índice'}</span>
          </button>
          <button
            onClick={() => set({ currentStep: 3 })}
            className="px-4 py-2.5 rounded-lg border border-border hover:bg-slate-50 text-xs sm:text-sm font-semibold flex items-center gap-1.5 transition text-content-main"
          >
            <span>Ir a Alcance</span>
            <ArrowRight className="w-4 h-4" />
          </button>
        </div>
      </div>

      <div className="bg-surface p-5 rounded-xl border border-border shadow-sm space-y-4">
        <h3 className="text-xs sm:text-sm font-bold text-content-main flex items-center gap-2">
          <Search className="w-4 h-4 text-primary" />
          <span>Probar Búsqueda Semántica y Reranking en Vivo</span>
        </h3>

        <div className="flex flex-col sm:flex-row gap-2">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyUp={(e) => e.key === 'Enter' && void searchTest(query)}
            placeholder="Ejemplo: política de crédito y evaluación de capacidad de pago del deudor..."
            className="flex-1 px-3.5 py-2 rounded-lg border border-border text-xs sm:text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary"
          />
          <button
            onClick={() => void searchTest(query)}
            className="px-4 py-2 rounded-lg bg-slate-900 hover:bg-slate-800 text-white text-xs sm:text-sm font-semibold transition flex items-center justify-center gap-1.5"
          >
            <Search className="w-4 h-4" />
            <span>Consultar</span>
          </button>
        </div>

        {results.length > 0 && (
          <div className="space-y-3 pt-2">
            {results.map((res) => (
              <div
                key={res.element_id}
                className="p-3 rounded-lg border border-border hover:border-primary/40 bg-slate-50/50 hover:bg-white transition space-y-2 text-xs"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center space-x-2">
                    <span className="px-2 py-0.5 rounded bg-blue-100 text-blue-800 font-bold font-mono">Art. {res.numero}</span>
                    <span className="font-semibold text-content-main">{res.encabezado}</span>
                  </div>
                  <span className="font-mono text-primary font-bold">score: {res.score.toFixed(3)}</span>
                </div>
                <p className="text-content-muted leading-relaxed line-clamp-2">{res.contenido}</p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
