<template>
  <div class="flex flex-col h-full bg-slate-900 text-white rounded-xl overflow-hidden shadow-2xl border border-slate-700">
    <!-- Barra de Herramientas del Visor -->
    <div class="bg-slate-800 px-4 py-2.5 flex items-center justify-between border-b border-slate-700 select-none">
      <div class="flex items-center space-x-2">
        <FileText class="w-4 h-4 text-primary-light" />
        <span class="text-xs sm:text-sm font-semibold truncate max-w-[200px] sm:max-w-xs text-slate-200">
          {{ docId }}
        </span>
        <span v-if="titulo" class="text-xs text-slate-400 hidden sm:inline">· {{ titulo }}</span>
      </div>

      <!-- Controles de Página y Zoom -->
      <div class="flex items-center space-x-2 sm:space-x-4">
        <!-- Navegación de páginas -->
        <div class="flex items-center space-x-1 text-xs">
          <button
            @click="prevPage"
            :disabled="currentPage <= 1 || loading"
            class="p-1 rounded hover:bg-slate-700 disabled:opacity-40 transition"
            title="Página anterior"
          >
            <ChevronLeft class="w-4 h-4" />
          </button>
          <span class="px-1 font-mono">
            {{ currentPage }} / {{ totalPages || 1 }}
          </span>
          <button
            @click="nextPage"
            :disabled="currentPage >= totalPages || loading"
            class="p-1 rounded hover:bg-slate-700 disabled:opacity-40 transition"
            title="Página siguiente"
          >
            <ChevronRight class="w-4 h-4" />
          </button>
        </div>

        <!-- Zoom -->
        <div class="flex items-center space-x-1 border-l border-slate-700 pl-2">
          <button
            @click="zoomOut"
            :disabled="scale <= 0.6 || loading"
            class="p-1 rounded hover:bg-slate-700 disabled:opacity-40 transition"
            title="Reducir zoom"
          >
            <ZoomOut class="w-4 h-4" />
          </button>
          <span class="text-xs font-mono w-10 text-center">{{ Math.round(scale * 100) }}%</span>
          <button
            @click="zoomIn"
            :disabled="scale >= 2.5 || loading"
            class="p-1 rounded hover:bg-slate-700 disabled:opacity-40 transition"
            title="Aumentar zoom"
          >
            <ZoomIn class="w-4 h-4" />
          </button>
        </div>

        <!-- Botón cerrar (si está en modal) -->
        <button
          v-if="closable"
          @click="$emit('close')"
          class="p-1 text-slate-400 hover:text-white rounded hover:bg-slate-700 transition"
          title="Cerrar visor"
        >
          <X class="w-5 h-5" />
        </button>
      </div>
    </div>

    <!-- Área de Renderizado Canvas -->
    <div
      ref="containerRef"
      class="flex-1 overflow-auto p-4 flex justify-center items-start bg-slate-950 relative select-none"
    >
      <div v-if="loading" class="absolute inset-0 flex flex-col items-center justify-center bg-slate-900/80 z-20 gap-3">
        <Loader2 class="w-8 h-8 text-primary animate-spin" />
        <span class="text-xs text-slate-300">Cargando documento PDF...</span>
      </div>

      <div v-if="error" class="text-center p-8 text-rose-400 max-w-sm my-auto">
        <AlertTriangle class="w-10 h-10 mx-auto mb-2 text-rose-400" />
        <p class="text-xs sm:text-sm font-medium">{{ error }}</p>
      </div>

      <!-- Contenedor relativo de Canvas + Overlay SVG -->
      <div v-show="!loading && !error" class="relative shadow-2xl rounded border border-slate-700/60 bg-white">
        <canvas ref="canvasRef" class="block"></canvas>

        <!-- Capa de resaltado (Bounding Box de la evidencia) -->
        <div
          v-if="bbox && currentPage === targetPage"
          class="absolute border-2 border-amber-500 bg-amber-400/25 rounded pointer-events-none transition-all animate-pulse"
          :style="bboxStyle"
        >
          <div class="absolute -top-6 left-0 bg-amber-500 text-slate-950 text-[10px] font-bold px-1.5 py-0.5 rounded shadow whitespace-nowrap">
            🎯 Evidencia citada
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import {
  FileText,
  ChevronLeft,
  ChevronRight,
  ZoomIn,
  ZoomOut,
  X,
  Loader2,
  AlertTriangle,
} from 'lucide-vue-next'
import * as pdfjsLib from 'pdfjs-dist'

// Configurar worker de pdfjs local
pdfjsLib.GlobalWorkerOptions.workerSrc = '/pdf.worker.min.js'

const props = defineProps<{
  tipo: 'normativa' | 'manual'
  docId: string
  initialPage?: number
  bbox?: [number, number, number, number]
  titulo?: string
  closable?: boolean
}>()

defineEmits(['close'])

const containerRef = ref<HTMLDivElement | null>(null)
const canvasRef = ref<HTMLCanvasElement | null>(null)

const loading = ref(true)
const error = ref<string | null>(null)
const currentPage = ref(props.initialPage || 1)
const targetPage = ref(props.initialPage || 1)
const totalPages = ref(1)
const scale = ref(1.2)

let pdfDoc: pdfjsLib.PDFDocumentProxy | null = null

const bboxStyle = computed(() => {
  if (!props.bbox || !canvasRef.value) return {}
  const [x1, y1, x2, y2] = props.bbox
  // Bbox relativo o porcentual
  return {
    left: `${x1 * 100}%`,
    top: `${y1 * 100}%`,
    width: `${(x2 - x1) * 100}%`,
    height: `${(y2 - y1) * 100}%`,
  }
})

async function loadPdf() {
  loading.value = true
  error.value = null
  const url = `/api/documents/${props.tipo}/${props.docId}/pdf`

  try {
    const loadingTask = pdfjsLib.getDocument({
      url,
      cMapUrl: 'https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/cmaps/',
      cMapPacked: true,
    })
    pdfDoc = await loadingTask.promise
    totalPages.value = pdfDoc.numPages
    currentPage.value = Math.min(Math.max(1, props.initialPage || 1), totalPages.value)
    targetPage.value = currentPage.value
    await renderPage(currentPage.value)
  } catch (err: any) {
    console.error('Error cargando PDF:', err)
    error.value = `No se pudo renderizar el PDF: ${err.message || 'Error desconocido'}`
  } finally {
    loading.value = false
  }
}

async function renderPage(pageNum: number) {
  if (!pdfDoc || !canvasRef.value) return
  try {
    const page = await pdfDoc.getPage(pageNum)
    const viewport = page.getViewport({ scale: scale.value })

    const canvas = canvasRef.value
    const context = canvas.getContext('2d')
    if (!context) return

    canvas.height = viewport.height
    canvas.width = viewport.width

    const renderContext = {
      canvasContext: context,
      viewport: viewport,
    }

    await page.render(renderContext).promise
  } catch (err) {
    console.error('Error al renderizar página:', err)
  }
}

function prevPage() {
  if (currentPage.value > 1) {
    currentPage.value--
    renderPage(currentPage.value)
  }
}

function nextPage() {
  if (currentPage.value < totalPages.value) {
    currentPage.value++
    renderPage(currentPage.value)
  }
}

function zoomIn() {
  scale.value = Math.min(2.5, scale.value + 0.2)
  renderPage(currentPage.value)
}

function zoomOut() {
  scale.value = Math.max(0.6, scale.value - 0.2)
  renderPage(currentPage.value)
}

watch(() => props.docId, () => {
  loadPdf()
})

watch(() => props.initialPage, (newVal) => {
  if (newVal && newVal !== currentPage.value) {
    currentPage.value = newVal
    targetPage.value = newVal
    renderPage(newVal)
  }
})

onMounted(() => {
  loadPdf()
})
</script>
