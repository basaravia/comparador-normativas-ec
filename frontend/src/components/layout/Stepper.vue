<template>
  <div class="bg-surface border-b border-border py-3 px-4 shadow-sm">
    <div class="max-w-7xl mx-auto flex items-center justify-between overflow-x-auto no-scrollbar">
      <div
        v-for="(step, idx) in steps"
        :key="step.number"
        class="flex items-center space-x-2 sm:space-x-3 cursor-pointer py-1 px-2 rounded-lg transition"
        :class="[
          store.currentStep === step.number
            ? 'bg-primary-light text-primary font-semibold'
            : store.currentStep > step.number
            ? 'text-slate-700 hover:bg-slate-50'
            : 'text-slate-400 opacity-80 cursor-default'
        ]"
        @click="goToStep(step.number)"
      >
        <div
          class="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold transition"
          :class="[
            store.currentStep === step.number
              ? 'bg-primary text-white shadow'
              : store.currentStep > step.number
              ? 'bg-emerald-500 text-white'
              : 'bg-slate-200 text-slate-500'
          ]"
        >
          <Check v-if="store.currentStep > step.number" class="w-4 h-4" />
          <span v-else>{{ step.number }}</span>
        </div>
        <div class="flex flex-col text-left">
          <span class="text-xs sm:text-sm whitespace-nowrap">{{ step.title }}</span>
          <span class="text-[10px] text-content-muted hidden md:inline">{{ step.desc }}</span>
        </div>
        <ChevronRight v-if="idx < steps.length - 1" class="w-4 h-4 text-slate-300 ml-2 hidden sm:block" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { Check, ChevronRight } from 'lucide-vue-next'
import { useAppStore } from '@/stores/useAppStore'

const store = useAppStore()

const steps = [
  { number: 1, title: '1. Documentos', desc: 'Carga y tabulación Docling' },
  { number: 2, title: '2. Índice Semántico', desc: 'FAISS + Sub-chunking' },
  { number: 3, title: '3. Alcance & Comparación', desc: 'Doble vía N:N' },
  { number: 4, title: '4. Resultados & Auditoría', desc: 'Papel de Trabajo Excel' },
]

function goToStep(num: number) {
  // Solo permite navegar hacia atrás o al paso actual
  if (num <= store.currentStep) {
    store.currentStep = num
  }
}
</script>
