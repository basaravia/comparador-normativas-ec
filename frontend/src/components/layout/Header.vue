<template>
  <header class="bg-surface border-b border-border sticky top-0 z-30 shadow-sm">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
      <!-- Marca y Título -->
      <div class="flex items-center space-x-3">
        <div class="w-10 h-10 rounded-lg bg-primary flex items-center justify-center text-white shadow-md">
          <Scale class="w-6 h-6 text-white" />
        </div>
        <div>
          <h1 class="text-base sm:text-lg font-bold text-content-main leading-tight flex items-center gap-2">
            Comparador de Normativas
            <span class="text-xs font-semibold px-2 py-0.5 bg-primary-light text-primary rounded-full border border-blue-200">v4.0</span>
          </h1>
          <p class="text-xs text-content-muted hidden sm:block">Pipeline Bancario Ecuatoriano (SBS · BCE · SEPS · UAF)</p>
        </div>
      </div>

      <!-- Indicadores de Plataforma y Swagger -->
      <div class="flex items-center space-x-2 sm:space-x-3">
        <!-- Badge de dispositivo -->
        <div v-if="store.serverHealth" class="hidden md:flex items-center px-2.5 py-1 rounded-md bg-canvas border border-border text-xs text-content-muted gap-1.5">
          <Cpu class="w-3.5 h-3.5 text-primary" />
          <span class="font-medium uppercase">{{ store.serverHealth.device }}</span>
          <span class="text-slate-300">|</span>
          <span class="capitalize">{{ store.serverHealth.platform }}</span>
        </div>

        <!-- Enlace a Swagger UI -->
        <a
          href="/docs"
          target="_blank"
          class="flex items-center gap-1 px-3 py-1.5 rounded-lg border border-border text-xs font-medium text-content-main hover:bg-slate-50 transition"
          title="Ver documentación Swagger OpenAPI interactiva"
        >
          <BookOpen class="w-4 h-4 text-blue-600" />
          <span class="hidden sm:inline">Swagger UI</span>
        </a>

        <!-- Enlace a Postman -->
        <a
          href="/api/postman.json"
          download="normativas_api.postman_collection.json"
          class="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-slate-900 text-white text-xs font-medium hover:bg-slate-800 transition shadow-sm"
          title="Descargar colección Postman v2.1"
        >
          <Download class="w-4 h-4" />
          <span class="hidden sm:inline">Postman</span>
        </a>
      </div>
    </div>
  </header>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { Scale, Cpu, BookOpen, Download } from 'lucide-vue-next'
import { useAppStore } from '@/stores/useAppStore'

const store = useAppStore()

onMounted(() => {
  store.fetchHealth()
})
</script>
