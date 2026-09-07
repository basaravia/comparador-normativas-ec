<template>
  <div class="space-y-6">
    <!-- Estado de Progreso en Vivo (SSE) -->
    <div
      v-if="store.isComparing"
      class="bg-surface p-6 rounded-xl border border-primary/30 shadow-md space-y-4 animate-pulse"
    >
      <div class="flex items-center justify-between text-xs sm:text-sm">
        <span class="font-bold text-primary flex items-center gap-2">
          <Loader2 class="w-4 h-4 animate-spin" />
          <span>{{ store.progressLabel || 'Analizando cumplimiento normativo...' }}</span>
        </span>
        <span class="font-mono font-bold text-primary">{{ store.progressPct }}%</span>
      </div>
      <div class="w-full bg-slate-100 rounded-full h-2.5 overflow-hidden">
        <div
          class="bg-primary h-2.5 rounded-full transition-all duration-300"
          :style="{ width: `${store.progressPct}%` }"
        ></div>
      </div>
    </div>

    <!-- Resultados y KPIs -->
    <template v-if="store.runStatus">
      <!-- Tarjetas de Cobertura Global (Ítem 6) -->
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div class="p-4 rounded-xl bg-surface border border-border shadow-sm">
          <span class="text-xs text-content-muted font-medium block">🎯 Cobertura Global</span>
          <span class="text-2xl sm:text-3xl font-bold text-primary font-mono mt-1 block">
            {{ formatPercent(store.runStatus.cobertura_global) }}
          </span>
        </div>

        <div class="p-4 rounded-xl bg-surface border border-border shadow-sm">
          <span class="text-xs text-content-muted font-medium block">Artículos en Alcance</span>
          <span class="text-2xl sm:text-3xl font-bold text-content-main font-mono mt-1 block">
            {{ store.runStatus.total || store.runStatus.vista_normativa.length }}
          </span>
        </div>

        <div class="p-4 rounded-xl bg-surface border border-border shadow-sm">
          <span class="text-xs text-content-muted font-medium block">Artículos Cubiertos</span>
          <span class="text-2xl sm:text-3xl font-bold text-emerald-600 font-mono mt-1 block">
            {{ store.runStatus.vista_normativa.filter(a => a.cubierto).length }}
          </span>
        </div>

        <div class="p-4 rounded-xl bg-surface border border-border shadow-sm">
          <span class="text-xs text-content-muted font-medium block">Sin Cobertura (Huérfanos)</span>
          <span class="text-2xl sm:text-3xl font-bold text-rose-600 font-mono mt-1 block">
            {{ store.runStatus.articulos_sin_cobertura.length }}
          </span>
        </div>
      </div>

      <!-- Alerta de Cobertura Incompleta (Premisa Bloque A) -->
      <div
        v-if="store.runStatus.alerta_cobertura"
        class="p-4 rounded-xl bg-rose-50 border border-rose-200 text-rose-900 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 shadow-sm"
      >
        <div class="flex items-center space-x-2.5">
          <AlertTriangle class="w-5 h-5 text-rose-600 shrink-0" />
          <span class="text-xs sm:text-sm font-semibold">{{ store.runStatus.alerta_cobertura }}</span>
        </div>
        <span class="text-xs bg-rose-200/80 text-rose-950 font-bold px-2 py-1 rounded">Requiere Atención</span>
      </div>

      <!-- Barra de Filtros y Descargas -->
      <div class="bg-surface p-4 rounded-xl border border-border shadow-sm flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <!-- Filtro Revisión Manual (Ítem 10) -->
        <div class="flex items-center space-x-2.5">
          <input
            v-model="store.filterSoloRevision"
            type="checkbox"
            id="chk_rev"
            class="rounded text-amber-600 focus:ring-amber-500 w-4 h-4 cursor-pointer"
          />
          <label for="chk_rev" class="text-xs sm:text-sm font-semibold text-content-main cursor-pointer flex items-center gap-1.5">
            <span>Solo filas que requieren revisión manual</span>
            <span class="px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 text-xs font-bold border border-amber-300">
              {{ store.runStatus.total_revision_manual }}
            </span>
          </label>
        </div>

        <!-- Botones de Exportación -->
        <div class="flex items-center space-x-2 w-full sm:w-auto">
          <a
            :href="`/api/compare/runs/${store.activeRunId}/export/excel`"
            download
            class="flex-1 sm:flex-none px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold flex items-center justify-center gap-2 shadow-sm transition"
          >
            <FileSpreadsheet class="w-4 h-4" />
            <span>Papel de Trabajo Excel (6 Hojas)</span>
          </a>
          <a
            :href="`/api/compare/runs/${store.activeRunId}/export/json`"
            download
            class="px-3 py-2 rounded-lg border border-border hover:bg-slate-50 text-xs font-semibold text-content-main transition"
          >
            JSON
          </a>
        </div>
      </div>

      <!-- Sub-Pestañas Vía 1 y Vía 2 -->
      <div class="bg-surface rounded-xl border border-border shadow-sm overflow-hidden">
        <div class="flex border-b border-border bg-slate-50 text-xs font-bold">
          <button
            @click="activeTab = 'via1'"
            class="py-3 px-5 transition border-b-2"
            :class="activeTab === 'via1' ? 'border-primary text-primary bg-white' : 'border-transparent text-content-muted hover:text-content-main'"
          >
            📋 Por Sección (Vía 1: Manual → Normativa)
          </button>
          <button
            @click="activeTab = 'via2'"
            class="py-3 px-5 transition border-b-2"
            :class="activeTab === 'via2' ? 'border-primary text-primary bg-white' : 'border-transparent text-content-muted hover:text-content-main'"
          >
            📜 Por Artículo (Vía 2: Normativa → Manual)
          </button>
        </div>

        <!-- Tabla Vía 1 -->
        <div v-if="activeTab === 'via1'" class="overflow-x-auto">
          <table class="w-full text-left text-xs">
            <thead class="bg-slate-100/70 border-b border-border text-slate-700 font-semibold uppercase text-[10px]">
              <tr>
                <th class="py-2.5 px-3">Jerarquía</th>
                <th class="py-2.5 px-3">Sección</th>
                <th class="py-2.5 px-3">Nivel Cumplimiento</th>
                <th class="py-2.5 px-3">Artículos</th>
                <th class="py-2.5 px-3">Revisión</th>
                <th class="py-2.5 px-3 text-right">Acción</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-border">
              <tr
                v-for="row in filteredV1"
                :key="row.chunk_id"
                class="hover:bg-slate-50 transition cursor-pointer"
                @click="store.openChunkInspector(row)"
              >
                <td class="py-2.5 px-3 font-mono font-medium">{{ row.jerarquia }}</td>
                <td class="py-2.5 px-3 font-medium text-content-main">{{ row.titulo_seccion }}</td>
                <td class="py-2.5 px-3">
                  <span
                    class="px-2 py-0.5 rounded text-[11px] font-bold uppercase"
                    :class="nivelClass(row.nivel_cumplimiento)"
                  >
                    {{ row.nivel_cumplimiento }}
                  </span>
                </td>
                <td class="py-2.5 px-3 font-mono">{{ formatList(row.articulos) }}</td>
                <td class="py-2.5 px-3">
                  <span
                    v-if="row.requiere_revision_manual"
                    class="px-2 py-0.5 rounded bg-amber-100 text-amber-900 font-bold text-[10px]"
                  >
                    ⚠️ Revisar
                  </span>
                  <span v-else class="text-slate-400">—</span>
                </td>
                <td class="py-2.5 px-3 text-right">
                  <button
                    @click.stop="abrirRowPdf('manual', row)"
                    class="p-1 rounded hover:bg-slate-200 text-primary"
                    title="Ver en PDF"
                  >
                    <ExternalLink class="w-4 h-4" />
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Tabla Vía 2 -->
        <div v-if="activeTab === 'via2'" class="overflow-x-auto">
          <table class="w-full text-left text-xs">
            <thead class="bg-slate-100/70 border-b border-border text-slate-700 font-semibold uppercase text-[10px]">
              <tr>
                <th class="py-2.5 px-3">Normativa</th>
                <th class="py-2.5 px-3">Artículo</th>
                <th class="py-2.5 px-3">Epígrafe</th>
                <th class="py-2.5 px-3">Cobertura</th>
                <th class="py-2.5 px-3">Revisión</th>
                <th class="py-2.5 px-3 text-right">Acción</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-border">
              <tr
                v-for="row in filteredV2"
                :key="row.element_id"
                class="hover:bg-slate-50 transition cursor-pointer"
                @click="store.openChunkInspector(row)"
              >
                <td class="py-2.5 px-3 font-mono">{{ row.articulo_doc_id }}</td>
                <td class="py-2.5 px-3 font-bold font-mono text-emerald-800">Art. {{ row.numero }}</td>
                <td class="py-2.5 px-3 font-medium text-content-main">{{ row.encabezado }}</td>
                <td class="py-2.5 px-3">
                  <span
                    class="px-2 py-0.5 rounded text-[11px] font-bold"
                    :class="row.cubierto ? 'bg-emerald-100 text-emerald-800' : 'bg-rose-100 text-rose-800'"
                  >
                    {{ row.cubierto ? 'Cubierto' : 'No Cubierto' }}
                  </span>
                </td>
                <td class="py-2.5 px-3">
                  <span
                    v-if="row.requiere_revision_manual"
                    class="px-2 py-0.5 rounded bg-amber-100 text-amber-900 font-bold text-[10px]"
                  >
                    ⚠️ Revisar
                  </span>
                  <span v-else class="text-slate-400">—</span>
                </td>
                <td class="py-2.5 px-3 text-right">
                  <button
                    @click.stop="abrirRowPdf('normativa', row)"
                    class="p-1 rounded hover:bg-slate-200 text-primary"
                    title="Ver en PDF"
                  >
                    <ExternalLink class="w-4 h-4" />
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import {
  Loader2,
  AlertTriangle,
  FileSpreadsheet,
  ExternalLink,
} from 'lucide-vue-next'
import { useAppStore } from '@/stores/useAppStore'

const store = useAppStore()
const activeTab = ref<'via1' | 'via2'>('via1')

const filteredV1 = computed(() => {
  if (!store.runStatus) return []
  let list = store.runStatus.vista_manual || []
  if (store.filterSoloRevision) {
    list = list.filter(r => r.requiere_revision_manual)
  }
  return list
})

const filteredV2 = computed(() => {
  if (!store.runStatus) return []
  let list = store.runStatus.vista_normativa || []
  if (store.filterSoloRevision) {
    list = list.filter(r => r.requiere_revision_manual)
  }
  return list
})

function formatPercent(val?: number): string {
  if (val === undefined || val === null) return '0.0%'
  return (val * 100).toFixed(1) + '%'
}

function formatList(val: any): string {
  if (Array.isArray(val)) return val.join(', ') || '—'
  return String(val || '—')
}

function nivelClass(nivel?: string): string {
  const n = String(nivel).toLowerCase()
  if (n === 'cumple') return 'bg-emerald-100 text-emerald-800'
  if (n === 'parcial') return 'bg-amber-100 text-amber-800'
  if (n === 'omision') return 'bg-rose-100 text-rose-800'
  return 'bg-slate-100 text-slate-800'
}

function abrirRowPdf(tipo: 'normativa' | 'manual', row: any) {
  const docId = row.doc_id || row.seccion_doc_id || row.articulo_doc_id
  const page = row.pagina_inicio || row.pagina || 1
  store.openPdfViewer(tipo, docId, page, row.bbox, row.jerarquia || row.encabezado)
}
</script>
