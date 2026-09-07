<template>
  <div class="space-y-6">
    <!-- Encabezado de Paso con Cuadro de Información -->
    <div class="bg-surface p-5 rounded-xl border border-border shadow-sm flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
      <div>
        <h2 class="text-base sm:text-lg font-bold text-content-main flex items-center gap-2">
          <span>📄 Paso 1: Carga y Tabulación de Documentos</span>
        </h2>
        <p class="text-xs sm:text-sm text-content-muted mt-1">
          Selecciona las normativas y manuales en PDF para procesar su estructura con Docling.
        </p>
      </div>

      <button
        @click="store.tabulate"
        :disabled="store.isTabulating || store.selectedNormativas.length === 0 || store.selectedManuales.length === 0"
        class="w-full sm:w-auto px-5 py-2.5 rounded-lg bg-primary hover:bg-primary-hover text-white text-xs sm:text-sm font-semibold flex items-center justify-center gap-2 shadow transition disabled:opacity-50"
      >
        <Loader2 v-if="store.isTabulating" class="w-4 h-4 animate-spin" />
        <Play v-else class="w-4 h-4 fill-current" />
        <span>{{ store.isTabulating ? 'Tabulando con Docling…' : 'Tabular Documentos' }}</span>
      </button>
    </div>

    <!-- Columnas de Selección de Documentos -->
    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
      <!-- Columna 1: Normativas -->
      <div class="bg-surface rounded-xl border border-border p-5 shadow-sm space-y-4">
        <div class="flex items-center justify-between border-b border-border pb-3">
          <div class="flex items-center space-x-2">
            <Scale class="w-5 h-5 text-blue-600" />
            <h3 class="font-bold text-sm text-content-main">Normativas Oficiales (SBS, BCE, SEPS)</h3>
          </div>
          <span class="text-xs px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 font-semibold border border-blue-200">
            {{ store.normativas.length }} disponibles
          </span>
        </div>

        <div class="space-y-2 max-h-64 overflow-y-auto pr-1">
          <div
            v-for="doc in store.normativas"
            :key="doc.id"
            class="flex items-center justify-between p-2.5 rounded-lg border border-border hover:bg-slate-50 transition text-xs cursor-pointer"
            @click="toggleNormativa(doc.id)"
          >
            <div class="flex items-center space-x-2.5">
              <input
                type="checkbox"
                :checked="store.selectedNormativas.includes(doc.id)"
                class="rounded border-slate-300 text-primary focus:ring-primary w-4 h-4"
              />
              <span class="font-medium text-content-main">{{ doc.id }}</span>
            </div>
            <button
              @click.stop="store.openPdfViewer('normativa', doc.id, 1, undefined, doc.nombre)"
              class="text-blue-600 hover:text-blue-800 p-1 rounded hover:bg-blue-50"
              title="Previsualizar PDF"
            >
              <Eye class="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      <!-- Columna 2: Manuales Internos -->
      <div class="bg-surface rounded-xl border border-border p-5 shadow-sm space-y-4">
        <div class="flex items-center justify-between border-b border-border pb-3">
          <div class="flex items-center space-x-2">
            <BookMarked class="w-5 h-5 text-indigo-600" />
            <h3 class="font-bold text-sm text-content-main">Manuales Internos Bancarios</h3>
          </div>
          <span class="text-xs px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-700 font-semibold border border-indigo-200">
            {{ store.manuales.length }} disponibles
          </span>
        </div>

        <div class="space-y-2 max-h-64 overflow-y-auto pr-1">
          <div
            v-for="doc in store.manuales"
            :key="doc.id"
            class="flex items-center justify-between p-2.5 rounded-lg border border-border hover:bg-slate-50 transition text-xs cursor-pointer"
            @click="toggleManual(doc.id)"
          >
            <div class="flex items-center space-x-2.5">
              <input
                type="checkbox"
                :checked="store.selectedManuales.includes(doc.id)"
                class="rounded border-slate-300 text-primary focus:ring-primary w-4 h-4"
              />
              <span class="font-medium text-content-main">{{ doc.id }}</span>
            </div>
            <button
              @click.stop="store.openPdfViewer('manual', doc.id, 1, undefined, doc.nombre)"
              class="text-indigo-600 hover:text-indigo-800 p-1 rounded hover:bg-indigo-50"
              title="Previsualizar PDF"
            >
              <Eye class="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { Scale, BookMarked, Play, Loader2, Eye } from 'lucide-vue-next'
import { useAppStore } from '@/stores/useAppStore'

const store = useAppStore()

function toggleNormativa(id: string) {
  const idx = store.selectedNormativas.indexOf(id)
  if (idx >= 0) store.selectedNormativas.splice(idx, 1)
  else store.selectedNormativas.push(id)
}

function toggleManual(id: string) {
  const idx = store.selectedManuales.indexOf(id)
  if (idx >= 0) store.selectedManuales.splice(idx, 1)
  else store.selectedManuales.push(id)
}

onMounted(() => {
  store.fetchDocuments()
})
</script>
