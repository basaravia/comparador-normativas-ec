<template>
  <div class="min-h-[80vh] flex items-center justify-center p-4">
    <div class="w-full max-w-md bg-surface p-6 sm:p-8 rounded-2xl border border-border shadow-xl space-y-6">
      <div class="text-center space-y-2">
        <div class="w-12 h-12 rounded-xl bg-primary flex items-center justify-center text-white mx-auto shadow-md">
          <Lock class="w-6 h-6" />
        </div>
        <h2 class="text-xl font-bold text-content-main">Acceso al Sistema</h2>
        <p class="text-xs text-content-muted">
          Ingrese sus credenciales autorizadas para acceder al Comparador de Normativas.
        </p>
      </div>

      <div
        v-if="store.authError"
        class="p-3 rounded-lg bg-rose-50 border border-rose-200 text-rose-900 text-xs flex items-center gap-2"
      >
        <AlertTriangle class="w-4 h-4 text-rose-600 shrink-0" />
        <span>{{ store.authError }}</span>
      </div>

      <form @submit.prevent="handleSubmit" class="space-y-4 text-xs sm:text-sm">
        <div>
          <label class="block font-medium text-content-main mb-1">Usuario</label>
          <input
            v-model="username"
            type="text"
            required
            autocomplete="username"
            placeholder="Usuario asignado"
            class="w-full p-2.5 rounded-lg border border-border bg-canvas focus:ring-2 focus:ring-primary/20 focus:border-primary focus:outline-none"
          />
        </div>

        <div>
          <label class="block font-medium text-content-main mb-1">Contraseña</label>
          <input
            v-model="password"
            type="password"
            required
            autocomplete="current-password"
            placeholder="••••••••"
            class="w-full p-2.5 rounded-lg border border-border bg-canvas focus:ring-2 focus:ring-primary/20 focus:border-primary focus:outline-none"
          />
        </div>

        <button
          type="submit"
          :disabled="loading"
          class="w-full py-2.5 rounded-lg bg-primary hover:bg-primary-hover text-white font-semibold flex items-center justify-center gap-2 shadow-sm transition disabled:opacity-50"
        >
          <Loader2 v-if="loading" class="w-4 h-4 animate-spin" />
          <span>{{ loading ? 'Verificando acceso…' : 'Iniciar Sesión' }}</span>
        </button>
      </form>

      <div class="border-t border-border pt-4 text-center">
        <span class="text-[11px] text-content-muted">
          Protección de acceso HTTPS y sesión firmada segura
        </span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { Lock, AlertTriangle, Loader2 } from 'lucide-vue-next'
import { useAppStore } from '@/stores/useAppStore'

const store = useAppStore()
const username = ref('asaravia002')
const password = ref('')
const loading = ref(false)

async function handleSubmit() {
  if (!username.value || !password.value) return
  loading.value = true
  await store.login(username.value, password.value)
  loading.value = false
}
</script>
