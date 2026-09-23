import { BookOpen, Cpu, Scale } from 'lucide-react'
import { useAppStore } from '@/store/useAppStore'

export default function Header() {
  const health = useAppStore((s) => s.serverHealth)
  const perfil = useAppStore((s) => s.perfil)
  const perfilError = useAppStore((s) => s.perfilError)

  return (
    <header className="bg-surface border-b border-border sticky top-0 z-30 shadow-sm">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <div className="w-10 h-10 rounded-lg bg-primary flex items-center justify-center text-white shadow-md">
            <Scale className="w-6 h-6 text-white" />
          </div>
          <div>
            <h1 className="text-base sm:text-lg font-bold text-content-main leading-tight flex items-center gap-2">
              Comparador de Normativas
              {health?.version && (
                <span className="text-xs font-semibold px-2 py-0.5 bg-primary-light text-primary rounded-full border border-blue-200">
                  v{health.version}
                </span>
              )}
            </h1>
            <p className="text-xs text-content-muted hidden sm:block">
              Pipeline Bancario Ecuatoriano (SBS · BCE · SEPS · UAF)
            </p>
          </div>
        </div>

        <div className="flex items-center space-x-2 sm:space-x-3">
          {(perfil || perfilError) && (
            <div
              className={`hidden md:flex items-center px-2.5 py-1 rounded-md border text-xs gap-1.5 ${
                perfilError ? 'bg-rose-50 border-rose-200 text-rose-800' : 'bg-canvas border-border text-content-muted'
              }`}
              title={perfilError ?? `LLM: ${perfil?.llm} · Embeddings: ${perfil?.embeddings} · Reranker: local`}
            >
              <span className="font-medium">Perfil</span>
              <span className="font-mono text-primary">{perfilError ? 'inválido' : perfil?.nombre}</span>
              {perfil?.con_override && <span title="LLM_BACKEND o EMBED_BACKEND fuerzan un eje">*</span>}
            </div>
          )}

          {health && (
            <div className="hidden md:flex items-center px-2.5 py-1 rounded-md bg-canvas border border-border text-xs text-content-muted gap-1.5">
              <Cpu className="w-3.5 h-3.5 text-primary" />
              <span className="font-medium uppercase">{health.device}</span>
              <span className="text-slate-300">|</span>
              <span className="capitalize">{health.platform}</span>
            </div>
          )}

          <a
            href="/docs"
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1 px-3 py-1.5 rounded-lg border border-border text-xs font-medium text-content-main hover:bg-slate-50 transition"
            title="Documentación Swagger OpenAPI interactiva"
          >
            <BookOpen className="w-4 h-4 text-blue-600" />
            <span className="hidden sm:inline">Swagger UI</span>
          </a>

        </div>
      </div>
    </header>
  )
}
