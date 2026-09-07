<template>
  <div class="min-h-screen flex flex-col bg-canvas text-content-main selection:bg-primary-light selection:text-primary">
    <!-- Encabezado Principal -->
    <Header />

    <!-- Barra de Pasos (Stepper) -->
    <Stepper />

    <!-- Área de Contenido Principal -->
    <main class="flex-1 max-w-7xl w-full mx-auto p-4 sm:p-6 lg:p-8 space-y-6">
      <Step1Documents v-if="store.currentStep === 1" />
      <Step2Index v-else-if="store.currentStep === 2" />
      <Step3Scope v-else-if="store.currentStep === 3" />
      <Step4Results v-else-if="store.currentStep === 4" />
    </main>

    <!-- Modal de Visor de PDF (Pantalla Completa en Móvil / Gran Modal en Desktop e iPad) -->
    <div
      v-if="store.showPdfModal && store.activePdf"
      class="fixed inset-0 z-50 flex items-center justify-center p-2 sm:p-6 bg-slate-950/80 backdrop-blur-sm animate-in fade-in duration-200"
    >
      <div class="w-full max-w-5xl h-[92vh] flex flex-col rounded-xl overflow-hidden shadow-2xl">
        <PdfViewer
          :tipo="store.activePdf.tipo"
          :doc-id="store.activePdf.docId"
          :initial-page="store.activePdf.page"
          :bbox="store.activePdf.bbox"
          :titulo="store.activePdf.titulo"
          :closable="true"
          @close="store.showPdfModal = false"
        />
      </div>
    </div>

    <!-- Drawer Lateral de Inspector de Chunks -->
    <div
      v-if="store.showChunkDrawer && store.activeChunk"
      class="fixed inset-0 z-40 flex justify-end bg-slate-950/40 backdrop-blur-xs"
      @click.self="store.showChunkDrawer = false"
    >
      <div class="w-full sm:w-[480px] h-full shadow-2xl animate-in slide-in-from-right duration-250">
        <ChunkInspector
          :chunk="store.activeChunk"
          :closable="true"
          @close="store.showChunkDrawer = false"
        />
      </div>
    </div>

    <!-- Pie de Página -->
    <footer class="bg-surface border-t border-border py-4 px-6 text-center text-xs text-content-muted">
      <p>Comparador de Normativas vs Manuales Internos · Fase 2 (Vue 3 + FastAPI + PDF.js)</p>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import Header from '@/components/layout/Header.vue'
import Stepper from '@/components/layout/Stepper.vue'
import Step1Documents from '@/components/steps/Step1Documents.vue'
import Step2Index from '@/components/steps/Step2Index.vue'
import Step3Scope from '@/components/steps/Step3Scope.vue'
import Step4Results from '@/components/steps/Step4Results.vue'
import PdfViewer from '@/components/viewer/PdfViewer.vue'
import ChunkInspector from '@/components/viewer/ChunkInspector.vue'
import { useAppStore } from '@/stores/useAppStore'

const store = useAppStore()

onMounted(() => {
  store.fetchHealth()
})
</script>
