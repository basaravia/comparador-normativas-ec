import { BookMarked, Loader2, Play, Scale } from 'lucide-react'
import { useAppStore } from '@/store/useAppStore'
import type { DocumentItem, TipoDoc } from '@/types'

interface ColumnaProps {
  tipo: TipoDoc
  titulo: string
  docs: DocumentItem[]
  seleccion: string[]
  acento: 'blue' | 'indigo'
}

function Columna({ tipo, titulo, docs, seleccion, acento }: ColumnaProps) {
  const toggleDoc = useAppStore((s) => s.toggleDoc)
  const Icono = tipo === 'normativa' ? Scale : BookMarked
  const tono =
    acento === 'blue'
      ? { icono: 'text-blue-600', badge: 'bg-blue-50 text-blue-700 border-blue-200' }
      : { icono: 'text-indigo-600', badge: 'bg-indigo-50 text-indigo-700 border-indigo-200' }

  return (
    <div className="bg-surface rounded-xl border border-border p-5 shadow-sm space-y-4">
      <div className="flex items-center justify-between border-b border-border pb-3">
        <div className="flex items-center space-x-2">
          <Icono className={`w-5 h-5 ${tono.icono}`} />
          <h3 className="font-bold text-sm text-content-main">{titulo}</h3>
        </div>
        <span className={`text-xs px-2 py-0.5 rounded-full font-semibold border ${tono.badge}`}>
          {docs.length} disponibles
        </span>
      </div>

      <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
        {docs.map((doc) => (
          <div
            key={doc.id}
            onClick={() => toggleDoc(tipo, doc.id)}
            className="flex items-center justify-between p-2.5 rounded-lg border border-border hover:bg-slate-50 transition text-xs cursor-pointer"
          >
            <div className="flex items-center space-x-2.5">
              <input
                type="checkbox"
                checked={seleccion.includes(doc.id)}
                readOnly
                className="rounded border-slate-300 text-primary focus:ring-primary w-4 h-4"
              />
              <span className="font-medium text-content-main">{doc.id}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function Step1Documents() {
  const normativas = useAppStore((s) => s.normativas)
  const manuales = useAppStore((s) => s.manuales)
  const selN = useAppStore((s) => s.selectedNormativas)
  const selM = useAppStore((s) => s.selectedManuales)
  const isTabulating = useAppStore((s) => s.isTabulating)
  const tabulate = useAppStore((s) => s.tabulate)

  return (
    <div className="space-y-6">
      <div className="bg-surface p-5 rounded-xl border border-border shadow-sm flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-base sm:text-lg font-bold text-content-main">📄 Paso 1: Carga y Tabulación de Documentos</h2>
          <p className="text-xs sm:text-sm text-content-muted mt-1">
            Selecciona las normativas y manuales en PDF para procesar su estructura con Docling.
          </p>
        </div>
        <button
          onClick={() => void tabulate()}
          disabled={isTabulating || selN.length === 0 || selM.length === 0}
          className="w-full sm:w-auto px-5 py-2.5 rounded-lg bg-primary hover:bg-primary-hover text-white text-xs sm:text-sm font-semibold flex items-center justify-center gap-2 shadow transition disabled:opacity-50"
        >
          {isTabulating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4 fill-current" />}
          <span>{isTabulating ? 'Tabulando con Docling…' : 'Tabular Documentos'}</span>
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Columna tipo="normativa" titulo="Normativas Oficiales (SBS, BCE, SEPS)" docs={normativas} seleccion={selN} acento="blue" />
        <Columna tipo="manual" titulo="Manuales Internos Bancarios" docs={manuales} seleccion={selM} acento="indigo" />
      </div>
    </div>
  )
}
