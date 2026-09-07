<template>
  <div class="bg-surface rounded-xl border border-border shadow-md flex flex-col h-full overflow-hidden">
    <!-- Encabezado del Inspector -->
    <div class="px-4 py-3 bg-slate-50 border-b border-border flex items-center justify-between">
      <div class="flex items-center space-x-2">
        <Sparkles class="w-4 h-4 text-primary" />
        <h3 class="text-xs sm:text-sm font-bold text-content-main">Inspector de Evidencia & Chunk</h3>
      </div>
      <button
        v-if="closable"
        @click="$emit('close')"
        class="p-1 text-slate-400 hover:text-slate-700 rounded hover:bg-slate-200 transition"
      >
        <X class="w-4 h-4" />
      </button>
    </div>

    <!-- Contenido del Inspector con scroll -->
    <div class="p-4 flex-1 overflow-y-auto space-y-4 text-xs sm:text-sm">
      <div v-if="!chunk" class="text-center py-12 text-content-muted">
        <FileSearch class="w-8 h-8 mx-auto mb-2 opacity-50" />
        <p>Selecciona una fila o artículo para inspeccionar la evidencia.</p>
      </div>

      <template v-else>
        <!-- Alerta de Revisión Manual (Ítem 10) -->
        <div
          v-if="chunk.requiere_revision_manual"
          class="p-3 rounded-lg bg-amber-50 border border-amber-200 text-amber-900 flex items-start space-x-2"
        >
          <AlertCircle class="w-5 h-5 text-amber-600 shrink-0 mt-0.5" />
          <div class="space-y-1">
            <span class="font-bold text-xs uppercase tracking-wide">Requiere Revisión Manual</span>
            <p class="text-xs text-amber-800">
              Esta relación no puede cerrarse automáticamente y exige validación humana.
            </p>
            <div class="flex flex-wrap gap-1 mt-1">
              <span
                v-for="motivo in chunk.motivos_revision || []"
                :key="motivo"
                class="px-2 py-0.5 bg-amber-200/80 text-amber-950 font-mono text-[10px] rounded font-semibold"
              >
                {{ motivo }}
              </span>
            </div>
          </div>
        </div>

        <!-- Identificadores y Jerarquía -->
        <div class="bg-canvas p-3 rounded-lg border border-border space-y-1.5">
          <div class="flex items-center justify-between">
            <span class="text-xs text-content-muted">Documento Origen:</span>
            <span class="font-mono font-medium text-xs text-primary">{{ chunk.doc_id || chunk.seccion_doc_id || 'N/A' }}</span>
          </div>
          <div class="flex items-center justify-between">
            <span class="text-xs text-content-muted">Jerarquía / Ubicación:</span>
            <span class="font-medium text-xs text-content-main">{{ chunk.jerarquia || chunk.seccion_jerarquia || 'N/A' }}</span>
          </div>
          <div v-if="chunk.numero || chunk.articulo_numero" class="flex items-center justify-between">
            <span class="text-xs text-content-muted">Artículo Normativo:</span>
            <span class="font-bold text-xs text-emerald-700">Art. {{ chunk.numero || chunk.articulo_numero }}</span>
          </div>
        </div>

        <!-- Métricas de Coincidencia (Scores) -->
        <div class="grid grid-cols-2 sm:grid-cols-3 gap-2">
          <div class="p-2.5 rounded-lg border border-border bg-slate-50 text-center">
            <span class="text-[10px] text-content-muted uppercase block">Similitud</span>
            <span class="font-mono font-bold text-sm text-primary">
              {{ formatScore(chunk.score_semantico || chunk.score) }}
            </span>
          </div>
          <div class="p-2.5 rounded-lg border border-border bg-slate-50 text-center">
            <span class="text-[10px] text-content-muted uppercase block">Reranker</span>
            <span class="font-mono font-bold text-sm text-slate-700">
              {{ formatScore(chunk.score_reranker) }}
            </span>
          </div>
          <div class="p-2.5 rounded-lg border border-border bg-slate-50 text-center col-span-2 sm:col-span-1">
            <span class="text-[10px] text-content-muted uppercase block">Origen</span>
            <span class="font-mono text-xs font-semibold text-content-main uppercase">
              {{ chunk.origen || 'Automático' }}
            </span>
          </div>
        </div>

        <!-- Texto del Fragmento / Chunk -->
        <div class="space-y-1.5">
          <span class="text-xs font-bold text-content-main flex items-center gap-1.5">
            <FileText class="w-3.5 h-3.5 text-primary" />
            Texto de la Evidencia (Chunk):
          </span>
          <div class="p-3 bg-slate-900 text-slate-100 rounded-lg text-xs leading-relaxed font-mono whitespace-pre-wrap max-h-48 overflow-y-auto border border-slate-700 select-text">
            {{ chunk.chunk_text || chunk.contenido || chunk.embed_text || chunk.analisis_general || 'Sin texto registrado' }}
          </div>
        </div>

        <!-- Razonamiento / Análisis -->
        <div v-if="chunk.razon || chunk.analisis_general" class="space-y-1.5">
          <span class="text-xs font-bold text-content-main">Sustento del Análisis:</span>
          <p class="text-xs text-content-muted bg-slate-50 p-2.5 rounded border border-border">
            {{ chunk.razon || chunk.analisis_general }}
          </p>
        </div>

        <!-- Botón Ver en PDF -->
        <div class="pt-2">
          <button
            @click="abrirEnPdf"
            class="w-full py-2 px-3 rounded-lg bg-primary hover:bg-primary-hover text-white text-xs font-semibold flex items-center justify-center gap-2 shadow-sm transition"
          >
            <ExternalLink class="w-4 h-4" />
            <span>Abrir en Visor de PDF con Resaltado</span>
          </button>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import {
  Sparkles,
  FileSearch,
  FileText,
  AlertCircle,
  ExternalLink,
  X,
} from 'lucide-vue-next'
import { useAppStore } from '@/stores/useAppStore'

const props = defineProps<{
  chunk?: any
  closable?: boolean
}>()

defineEmits(['close'])

const store = useAppStore()

function formatScore(val: any): string {
  if (val === null || val === undefined || isNaN(Number(val))) return 'N/A'
  return Number(val).toFixed(3)
}

function abrirEnPdf() {
  if (!props.chunk) return
  const docId = props.chunk.doc_id || props.chunk.seccion_doc_id || props.chunk.articulo_doc_id
  const tipo = docId && docId.includes('MANUAL') ? 'manual' : 'normativa'
  const page = props.chunk.pagina_inicio || props.chunk.pagina || 1
  const titulo = props.chunk.jerarquia || props.chunk.encabezado || `Art. ${props.chunk.numero || ''}`
  store.openPdfViewer(tipo, docId, page, props.chunk.bbox, titulo)
}
</script>
