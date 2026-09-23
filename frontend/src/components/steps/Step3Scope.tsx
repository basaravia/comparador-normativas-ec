import { BookMarked, Rocket, Scale } from 'lucide-react'
import { useAppStore } from '@/store/useAppStore'

const MODOS = ['Muestra rápida', 'Todo el manual', 'Por jerarquía']
const campo =
  'w-full p-2 rounded-lg border border-border bg-canvas focus:ring-1 focus:ring-primary focus:outline-none'

export default function Step3Scope() {
  const s = useAppStore()

  return (
    <div className="space-y-6">
      <div className="bg-surface p-5 rounded-xl border border-border shadow-sm flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-base sm:text-lg font-bold text-content-main">🎯 Paso 3: Selector de Alcance & Configuración de Corrida</h2>
          <p className="text-xs sm:text-sm text-content-muted mt-1">
            Filtra exactamente qué artículos y qué secciones entrarán al análisis (Ítem 7).
          </p>
        </div>
        <button
          onClick={() => void s.startCompare()}
          disabled={s.isComparing}
          className="w-full sm:w-auto px-6 py-2.5 rounded-lg bg-primary hover:bg-primary-hover text-white text-xs sm:text-sm font-semibold flex items-center justify-center gap-2 shadow-md transition disabled:opacity-50"
        >
          <Rocket className="w-4 h-4" />
          <span>Iniciar Análisis Comparativo</span>
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="bg-surface rounded-xl border border-border p-5 shadow-sm space-y-4">
          <h3 className="font-bold text-sm text-content-main flex items-center gap-2 border-b border-border pb-2.5">
            <Scale className="w-4 h-4 text-blue-600" />
            <span>Alcance Normativo</span>
          </h3>
          <div className="space-y-3 text-xs">
            <div>
              <label htmlFor="preset" className="block font-medium text-content-main mb-1">Preset de articulado:</label>
              <select id="preset" value={s.scopePresetNorm} onChange={(e) => s.set({ scopePresetNorm: e.target.value })} className={campo}>
                <option value="Todo el articulado">Todo el articulado (incluye preámbulos y referencias)</option>
                <option value="Excluir referencias">Excluir referencias normativas cruzadas (Recomendado)</option>
                <option value="Solo disposiciones">Solo disposiciones transitorias y finales</option>
              </select>
            </div>
            <div>
              <label htmlFor="filtro" className="block font-medium text-content-main mb-1">Búsqueda / Filtro específico:</label>
              <input
                id="filtro"
                type="text"
                value={s.scopeSearchNorm}
                onChange={(e) => s.set({ scopeSearchNorm: e.target.value })}
                placeholder="Ej. Art. 35 o Crédito..."
                className={campo}
              />
            </div>
          </div>
        </div>

        <div className="bg-surface rounded-xl border border-border p-5 shadow-sm space-y-4">
          <h3 className="font-bold text-sm text-content-main flex items-center gap-2 border-b border-border pb-2.5">
            <BookMarked className="w-4 h-4 text-indigo-600" />
            <span>Alcance del Manual Interno</span>
          </h3>
          <div className="space-y-3 text-xs">
            <div>
              <span className="block font-medium text-content-main mb-1">Modo de selección de secciones:</span>
              <div className="grid grid-cols-3 gap-2">
                {MODOS.map((modo) => (
                  <button
                    key={modo}
                    type="button"
                    onClick={() => s.set({ scopeModoManual: modo })}
                    className={`py-1.5 px-2 rounded-lg border text-center font-medium transition ${
                      s.scopeModoManual === modo ? 'bg-primary-light border-primary text-primary font-bold' : 'border-border hover:bg-slate-50'
                    }`}
                  >
                    {modo}
                  </button>
                ))}
              </div>
            </div>

            {s.scopeModoManual === 'Muestra rápida' && (
              <div>
                <label htmlFor="muestra" className="block font-medium text-content-main mb-1">Número de secciones a procesar:</label>
                <input
                  id="muestra"
                  type="number"
                  min={1}
                  max={50}
                  value={s.scopeSampleSize}
                  onChange={(e) => s.set({ scopeSampleSize: Number(e.target.value) })}
                  className={campo}
                />
                <span className="text-[10px] text-content-muted mt-1 block">Toma las primeras N secciones del manual en orden documental.</span>
              </div>
            )}

            {s.scopeModoManual === 'Por jerarquía' && (
              <div>
                <label htmlFor="jerarquia" className="block font-medium text-content-main mb-1">Filtro de jerarquía o capítulo:</label>
                <input
                  id="jerarquia"
                  type="text"
                  value={s.scopeJerarquiaTxt}
                  onChange={(e) => s.set({ scopeJerarquiaTxt: e.target.value })}
                  placeholder="Ej. 4.1 o Riesgo Operativo"
                  className={campo}
                />
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="p-4 rounded-xl bg-blue-50/70 border border-blue-200 flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <input
            id="dual_toggle"
            type="checkbox"
            checked={s.dualMode}
            onChange={(e) => s.set({ dualMode: e.target.checked })}
            className="rounded text-primary focus:ring-primary w-5 h-5 cursor-pointer"
          />
          <label htmlFor="dual_toggle" className="cursor-pointer text-xs sm:text-sm text-blue-950 font-semibold">
            Análisis en Doble Vía (Ítem 6) — Vía 1 (manual → norma) + Vía 2 (norma → manual) y Cobertura Global
          </label>
        </div>
        <span className="text-xs px-2.5 py-1 rounded bg-blue-600 text-white font-bold hidden sm:inline">Recomendado</span>
      </div>
    </div>
  )
}
