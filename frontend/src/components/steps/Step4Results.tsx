import { useMemo, useState } from 'react'
import { AlertTriangle, FileSpreadsheet, Loader2 } from 'lucide-react'
import { urls } from '@/api/client'
import { useAppStore } from '@/store/useAppStore'
import type { Fila } from '@/types'

const pct = (v?: number | null) => (v == null ? '0.0%' : `${(v * 100).toFixed(1)}%`)
const lista = (v: unknown) => (Array.isArray(v) ? v.join(', ') || '—' : String(v || '—'))

function nivelClass(nivel?: string): string {
  switch (String(nivel).toLowerCase()) {
    case 'cumple': return 'bg-emerald-100 text-emerald-800'
    case 'parcial': return 'bg-amber-100 text-amber-800'
    case 'omision': return 'bg-rose-100 text-rose-800'
    default: return 'bg-slate-100 text-slate-800'
  }
}

function Kpi({ etiqueta, valor, color }: { etiqueta: string; valor: string | number; color: string }) {
  return (
    <div className="p-4 rounded-xl bg-surface border border-border shadow-sm">
      <span className="text-xs text-content-muted font-medium block">{etiqueta}</span>
      <span className={`text-2xl sm:text-3xl font-bold font-mono mt-1 block ${color}`}>{valor}</span>
    </div>
  )
}

function Revision({ fila }: { fila: Fila }) {
  return fila.requiere_revision_manual ? (
    <span className="px-2 py-0.5 rounded bg-amber-100 text-amber-900 font-bold text-[10px]">⚠️ Revisar</span>
  ) : (
    <span className="text-slate-400">—</span>
  )
}

export default function Step4Results() {
  const isComparing = useAppStore((s) => s.isComparing)
  const progressLabel = useAppStore((s) => s.progressLabel)
  const progressPct = useAppStore((s) => s.progressPct)
  const run = useAppStore((s) => s.runStatus)
  const runId = useAppStore((s) => s.activeRunId)
  const soloRevision = useAppStore((s) => s.filterSoloRevision)
  const set = useAppStore((s) => s.set)
  const [tab, setTab] = useState<'via1' | 'via2'>('via1')

  const v1 = useMemo(
    () => (run?.vista_manual ?? []).filter((r) => !soloRevision || r.requiere_revision_manual),
    [run, soloRevision],
  )
  const v2 = useMemo(
    () => (run?.vista_normativa ?? []).filter((r) => !soloRevision || r.requiere_revision_manual),
    [run, soloRevision],
  )

  const th = 'py-2.5 px-3'
  const thead = 'bg-slate-100/70 border-b border-border text-slate-700 font-semibold uppercase text-[10px]'
  const tabBtn = (activa: boolean) =>
    `py-3 px-5 transition border-b-2 ${activa ? 'border-primary text-primary bg-white' : 'border-transparent text-content-muted hover:text-content-main'}`

  return (
    <div className="space-y-6">
      {isComparing && (
        <div className="bg-surface p-6 rounded-xl border border-primary/30 shadow-md space-y-4">
          <div className="flex items-center justify-between text-xs sm:text-sm">
            <span className="font-bold text-primary flex items-center gap-2">
              <Loader2 className="w-4 h-4 animate-spin" />
              <span>{progressLabel || 'Analizando cumplimiento normativo...'}</span>
            </span>
            <span className="font-mono font-bold text-primary">{progressPct}%</span>
          </div>
          <div className="w-full bg-slate-100 rounded-full h-2.5 overflow-hidden">
            <div className="bg-primary h-2.5 rounded-full transition-all duration-300" style={{ width: `${progressPct}%` }} />
          </div>
        </div>
      )}

      {run && (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
            <Kpi etiqueta="🎯 Cobertura Global" valor={pct(run.cobertura_global)} color="text-primary" />
            <Kpi etiqueta="Artículos en Alcance" valor={run.total || run.vista_normativa.length} color="text-content-main" />
            <Kpi etiqueta="Artículos Cubiertos" valor={run.vista_normativa.filter((a) => a.cubierto).length} color="text-emerald-600" />
            {/* "Cubiertos" cuenta el veredicto de adopción de la Vía 2; un artículo con cobertura
                parcial no entra ahí ni en "Huérfanos", así que necesita su propia tarjeta. */}
            <Kpi etiqueta="Cobertura Parcial" valor={(run.articulos_parciales ?? []).length} color="text-amber-600" />
            <Kpi etiqueta="Sin Cobertura (Huérfanos)" valor={run.articulos_sin_cobertura.length} color="text-rose-600" />
          </div>

          {run.alerta_cobertura && (
            <div className="p-4 rounded-xl bg-rose-50 border border-rose-200 text-rose-900 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 shadow-sm">
              <div className="flex items-center space-x-2.5">
                <AlertTriangle className="w-5 h-5 text-rose-600 shrink-0" />
                <span className="text-xs sm:text-sm font-semibold">{run.alerta_cobertura}</span>
              </div>
              <span className="text-xs bg-rose-200/80 text-rose-950 font-bold px-2 py-1 rounded">Requiere Atención</span>
            </div>
          )}

          <div className="bg-surface p-4 rounded-xl border border-border shadow-sm flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
            <div className="flex items-center space-x-2.5">
              <input
                id="chk_rev"
                type="checkbox"
                checked={soloRevision}
                onChange={(e) => set({ filterSoloRevision: e.target.checked })}
                className="rounded text-amber-600 focus:ring-amber-500 w-4 h-4 cursor-pointer"
              />
              <label htmlFor="chk_rev" className="text-xs sm:text-sm font-semibold text-content-main cursor-pointer flex items-center gap-1.5">
                <span>Solo filas que requieren revisión manual</span>
                <span className="px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 text-xs font-bold border border-amber-300">
                  {run.total_revision_manual}
                </span>
              </label>
            </div>

            {runId && (
              <div className="flex items-center space-x-2 w-full sm:w-auto">
                <a
                  href={urls.export(runId, 'excel')}
                  download
                  className="flex-1 sm:flex-none px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold flex items-center justify-center gap-2 shadow-sm transition"
                >
                  <FileSpreadsheet className="w-4 h-4" />
                  <span>Papel de Trabajo Excel (6 Hojas)</span>
                </a>
                <a
                  href={urls.export(runId, 'json')}
                  download
                  className="px-3 py-2 rounded-lg border border-border hover:bg-slate-50 text-xs font-semibold text-content-main transition"
                >
                  JSON
                </a>
              </div>
            )}
          </div>

          <div className="bg-surface rounded-xl border border-border shadow-sm overflow-hidden">
            <div className="flex border-b border-border bg-slate-50 text-xs font-bold">
              <button onClick={() => setTab('via1')} className={tabBtn(tab === 'via1')}>📋 Por Sección (Vía 1: Manual → Normativa)</button>
              <button onClick={() => setTab('via2')} className={tabBtn(tab === 'via2')}>📜 Por Artículo (Vía 2: Normativa → Manual)</button>
            </div>

            {tab === 'via1' ? (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className={thead}>
                    <tr>
                      <th className={th}>Jerarquía</th><th className={th}>Sección</th><th className={th}>Nivel Cumplimiento</th>
                      <th className={th}>Artículos</th><th className={th}>Revisión</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {v1.map((row) => (
                      <tr key={row.chunk_id} className="hover:bg-slate-50 transition">
                        <td className="py-2.5 px-3 font-mono font-medium">{row.jerarquia}</td>
                        <td className="py-2.5 px-3 font-medium text-content-main">{row.titulo_seccion}</td>
                        <td className="py-2.5 px-3">
                          <span className={`px-2 py-0.5 rounded text-[11px] font-bold uppercase ${nivelClass(row.nivel_cumplimiento)}`}>
                            {row.nivel_cumplimiento}
                          </span>
                        </td>
                        <td className="py-2.5 px-3 font-mono">{lista(row.articulos)}</td>
                        <td className="py-2.5 px-3"><Revision fila={row} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className={thead}>
                    <tr>
                      <th className={th}>Normativa</th><th className={th}>Artículo</th><th className={th}>Epígrafe</th>
                      <th className={th}>Cobertura</th><th className={th}>Revisión</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {v2.map((row) => (
                      <tr key={row.element_id} className="hover:bg-slate-50 transition">
                        <td className="py-2.5 px-3 font-mono">{row.articulo_doc_id}</td>
                        <td className="py-2.5 px-3 font-bold font-mono text-emerald-800">Art. {row.numero}</td>
                        <td className="py-2.5 px-3 font-medium text-content-main">{row.encabezado}</td>
                        <td className="py-2.5 px-3">
                          <span className={`px-2 py-0.5 rounded text-[11px] font-bold ${row.cubierto ? 'bg-emerald-100 text-emerald-800' : 'bg-rose-100 text-rose-800'}`}>
                            {row.cubierto ? 'Cubierto' : 'No Cubierto'}
                          </span>
                        </td>
                        <td className="py-2.5 px-3"><Revision fila={row} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
