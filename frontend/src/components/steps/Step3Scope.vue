<template>
  <div class="space-y-6">
    <div class="bg-surface p-5 rounded-xl border border-border shadow-sm flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
      <div>
        <h2 class="text-base sm:text-lg font-bold text-content-main flex items-center gap-2">
          <span>🎯 Paso 3: Selector de Alcance & Configuración de Corrida</span>
        </h2>
        <p class="text-xs sm:text-sm text-content-muted mt-1">
          Filtra exactamente qué artículos y qué secciones entrarán al análisis (Ítem 7).
        </p>
      </div>

      <button
        @click="store.startCompare"
        :disabled="store.isComparing"
        class="w-full sm:w-auto px-6 py-2.5 rounded-lg bg-primary hover:bg-primary-hover text-white text-xs sm:text-sm font-semibold flex items-center justify-center gap-2 shadow-md transition disabled:opacity-50"
      >
        <Rocket class="w-4 h-4" />
        <span>Iniciar Análisis Comparativo</span>
      </button>
    </div>

    <!-- Controles de Alcance -->
    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
      <!-- Alcance Normativo -->
      <div class="bg-surface rounded-xl border border-border p-5 shadow-sm space-y-4">
        <h3 class="font-bold text-sm text-content-main flex items-center gap-2 border-b border-border pb-2.5">
          <Scale class="w-4 h-4 text-blue-600" />
          <span>Alcance Normativo</span>
        </h3>

        <div class="space-y-3 text-xs">
          <div>
            <label class="block font-medium text-content-main mb-1">Preset de articulado:</label>
            <select
              v-model="store.scopePresetNorm"
              class="w-full p-2 rounded-lg border border-border bg-canvas focus:ring-1 focus:ring-primary focus:outline-none"
            >
              <option value="Todo el articulado">Todo el articulado (incluye preámbulos y referencias)</option>
              <option value="Excluir referencias">Excluir referencias normativas cruzadas (Recomendado)</option>
              <option value="Solo disposiciones">Solo disposiciones transitorias y finales</option>
            </select>
          </div>

          <div>
            <label class="block font-medium text-content-main mb-1">Búsqueda / Filtro específico:</label>
            <input
              v-model="store.scopeSearchNorm"
              type="text"
              placeholder="Ej. Art. 35 o Crédito..."
              class="w-full p-2 rounded-lg border border-border bg-canvas focus:ring-1 focus:ring-primary focus:outline-none"
            />
          </div>
        </div>
      </div>

      <!-- Alcance del Manual -->
      <div class="bg-surface rounded-xl border border-border p-5 shadow-sm space-y-4">
        <h3 class="font-bold text-sm text-content-main flex items-center gap-2 border-b border-border pb-2.5">
          <BookMarked class="w-4 h-4 text-indigo-600" />
          <span>Alcance del Manual Interno</span>
        </h3>

        <div class="space-y-3 text-xs">
          <div>
            <label class="block font-medium text-content-main mb-1">Modo de selección de secciones:</label>
            <div class="grid grid-cols-3 gap-2">
              <button
                v-for="modo in ['Muestra rápida', 'Todo el manual', 'Por jerarquía']"
                :key="modo"
                @click="store.scopeModoManual = modo"
                type="button"
                class="py-1.5 px-2 rounded-lg border text-center font-medium transition"
                :class="store.scopeModoManual === modo ? 'bg-primary-light border-primary text-primary font-bold' : 'border-border hover:bg-slate-50'"
              >
                {{ modo }}
              </button>
            </div>
          </div>

          <div v-if="store.scopeModoManual === 'Muestra rápida'">
            <label class="block font-medium text-content-main mb-1">Número de secciones a procesar:</label>
            <input
              v-model.number="store.scopeSampleSize"
              type="number"
              min="1"
              max="50"
              class="w-full p-2 rounded-lg border border-border bg-canvas focus:ring-1 focus:ring-primary focus:outline-none"
            />
            <span class="text-[10px] text-content-muted mt-1 block">Toma las primeras N secciones del manual en orden documental.</span>
          </div>

          <div v-if="store.scopeModoManual === 'Por jerarquía'">
            <label class="block font-medium text-content-main mb-1">Filtro de jerarquía o capítulo:</label>
            <input
              v-model="store.scopeJerarquiaTxt"
              type="text"
              placeholder="Ej. 4.1 o Riesgo Operativo"
              class="w-full p-2 rounded-lg border border-border bg-canvas focus:ring-1 focus:ring-primary focus:outline-none"
            />
          </div>
        </div>
      </div>
    </div>

    <!-- Opciones de Doble Vía -->
    <div class="p-4 rounded-xl bg-blue-50/70 border border-blue-200 flex items-center justify-between">
      <div class="flex items-center space-x-3">
        <input
          v-model="store.dualMode"
          type="checkbox"
          id="dual_toggle"
          class="rounded text-primary focus:ring-primary w-5 h-5 cursor-pointer"
        />
        <label for="dual_toggle" class="cursor-pointer text-xs sm:text-sm text-blue-950 font-semibold">
          Análisis en Doble Vía (Ítem 6) — Vía 1 (manual → norma) + Vía 2 (norma → manual) y Cobertura Global
        </label>
      </div>
      <span class="text-xs px-2.5 py-1 rounded bg-blue-600 text-white font-bold hidden sm:inline">Recomendado</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { Scale, BookMarked, Rocket } from 'lucide-vue-next'
import { useAppStore } from '@/stores/useAppStore'

const store = useAppStore()
</script>
