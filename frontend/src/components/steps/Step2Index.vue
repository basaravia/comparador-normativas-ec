<template>
  <div class="space-y-6">
    <div class="bg-surface p-5 rounded-xl border border-border shadow-sm flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
      <div>
        <h2 class="text-base sm:text-lg font-bold text-content-main flex items-center gap-2">
          <span>🧭 Paso 2: Índice Semántico Vectorial FAISS</span>
        </h2>
        <p class="text-xs sm:text-sm text-content-muted mt-1">
          Indexa los artículos con el modelo parent-child (Ítem 8) para optimizar el recall de fragmentos largos.
        </p>
      </div>

      <div class="flex items-center space-x-3 w-full sm:w-auto">
        <button
          @click="store.buildIndex"
          :disabled="store.isIndexing"
          class="flex-1 sm:flex-none px-5 py-2.5 rounded-lg bg-primary hover:bg-primary-hover text-white text-xs sm:text-sm font-semibold flex items-center justify-center gap-2 shadow transition disabled:opacity-50"
        >
          <Loader2 v-if="store.isIndexing" class="w-4 h-4 animate-spin" />
          <Database v-else class="w-4 h-4" />
          <span>{{ store.isIndexing ? 'Construyendo FAISS…' : (store.indexBuilt ? 'Reconstruir Índice' : 'Construir Índice') }}</span>
        </button>

        <button
          @click="store.currentStep = 3"
          class="px-4 py-2.5 rounded-lg border border-border hover:bg-slate-50 text-xs sm:text-sm font-semibold flex items-center gap-1.5 transition text-content-main"
        >
          <span>Ir a Alcance</span>
          <ArrowRight class="w-4 h-4" />
        </button>
      </div>
    </div>

    <!-- Buscador de Prueba -->
    <div class="bg-surface p-5 rounded-xl border border-border shadow-sm space-y-4">
      <h3 class="text-xs sm:text-sm font-bold text-content-main flex items-center gap-2">
        <Search class="w-4 h-4 text-primary" />
        <span>Probar Búsqueda Semántica y Reranking en Vivo</span>
      </h3>

      <div class="flex flex-col sm:flex-row gap-2">
        <input
          v-model="queryInput"
          type="text"
          placeholder="Ejemplo: política de crédito y evaluación de capacidad de pago del deudor..."
          class="flex-1 px-3.5 py-2 rounded-lg border border-border text-xs sm:text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary"
          @keyup.enter="handleSearch"
        />
        <button
          @click="handleSearch"
          class="px-4 py-2 rounded-lg bg-slate-900 hover:bg-slate-800 text-white text-xs sm:text-sm font-semibold transition flex items-center justify-center gap-1.5"
        >
          <Search class="w-4 h-4" />
          <span>Consultar</span>
        </button>
      </div>

      <!-- Resultados de Búsqueda -->
      <div v-if="store.searchResults.length > 0" class="space-y-3 pt-2">
        <div
          v-for="res in store.searchResults"
          :key="res.element_id"
          class="p-3 rounded-lg border border-border hover:border-primary/40 bg-slate-50/50 hover:bg-white transition space-y-2 text-xs"
        >
          <div class="flex items-center justify-between">
            <div class="flex items-center space-x-2">
              <span class="px-2 py-0.5 rounded bg-blue-100 text-blue-800 font-bold font-mono">
                Art. {{ res.numero }}
              </span>
              <span class="font-semibold text-content-main">{{ res.encabezado }}</span>
            </div>
            <span class="font-mono text-primary font-bold">score: {{ res.score.toFixed(3) }}</span>
          </div>

          <p class="text-content-muted leading-relaxed line-clamp-2">
            {{ res.contenido }}
          </p>

          <div class="flex justify-end gap-2 pt-1">
            <button
              @click="store.openChunkInspector(res)"
              class="px-2 py-1 rounded bg-slate-200 hover:bg-slate-300 text-slate-800 text-[11px] font-medium"
            >
              Inspeccionar Chunk
            </button>
            <button
              @click="store.openPdfViewer('normativa', res.doc_id, 1, undefined, res.encabezado)"
              class="px-2 py-1 rounded bg-primary-light hover:bg-blue-100 text-primary text-[11px] font-medium flex items-center gap-1"
            >
              <ExternalLink class="w-3 h-3" />
              Ver en PDF
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { Database, ArrowRight, Search, ExternalLink, Loader2 } from 'lucide-vue-next'
import { useAppStore } from '@/stores/useAppStore'

const store = useAppStore()
const queryInput = ref('política de crédito y evaluación de capacidad de pago')

function handleSearch() {
  store.searchTest(queryInput.value)
}
</script>
