import { useEffect } from 'react'
import { AlertTriangle, Loader2, X } from 'lucide-react'
import Header from '@/components/layout/Header'
import Stepper from '@/components/layout/Stepper'
import Step1Documents from '@/components/steps/Step1Documents'
import Step2Index from '@/components/steps/Step2Index'
import Step3Scope from '@/components/steps/Step3Scope'
import Step4Results from '@/components/steps/Step4Results'
import { useAppStore } from '@/store/useAppStore'

/** Interfaz mínima de prueba: los 4 pasos del pipeline, sin login, visor PDF ni inspector. */
export default function App() {
  const authChecking = useAppStore((s) => s.authChecking)
  const authBlocked = useAppStore((s) => s.authBlocked)
  const currentStep = useAppStore((s) => s.currentStep)
  const error = useAppStore((s) => s.error)
  const clearError = useAppStore((s) => s.clearError)

  useEffect(() => {
    const { fetchHealth, checkAuth } = useAppStore.getState()
    void fetchHealth().then(checkAuth)
  }, [])

  return (
    <div className="min-h-screen flex flex-col bg-canvas text-content-main">
      <Header />

      {authChecking ? (
        <div className="flex-1 flex flex-col items-center justify-center p-12 space-y-3">
          <Loader2 className="w-8 h-8 text-primary animate-spin" />
          <span className="text-xs text-content-muted">Conectando con la API...</span>
        </div>
      ) : authBlocked ? (
        <main className="flex-1 max-w-2xl w-full mx-auto p-8">
          <div role="alert" className="p-5 rounded-xl bg-amber-50 border border-amber-200 text-amber-900 space-y-2 text-sm">
            <p className="font-bold flex items-center gap-2">
              <AlertTriangle className="w-5 h-5 text-amber-600" /> La API exige sesión
            </p>
            <p>
              Esta interfaz mínima no tiene pantalla de acceso. Arranca el backend con{' '}
              <code className="font-mono bg-amber-100 px-1 rounded">AUTH_ENABLED=false</code> para probarla.
            </p>
          </div>
        </main>
      ) : (
        <>
          <Stepper />
          <main className="flex-1 max-w-7xl w-full mx-auto p-4 sm:p-6 lg:p-8 space-y-6">
            {error && (
              <div
                role="alert"
                className="p-3 rounded-xl bg-rose-50 border border-rose-200 text-rose-900 text-xs sm:text-sm flex items-start justify-between gap-3"
              >
                <span className="flex items-start gap-2">
                  <AlertTriangle className="w-4 h-4 text-rose-600 shrink-0 mt-0.5" />
                  <span>{error}</span>
                </span>
                <button onClick={clearError} className="text-rose-700 hover:text-rose-900" title="Cerrar">
                  <X className="w-4 h-4" />
                </button>
              </div>
            )}
            {currentStep === 1 && <Step1Documents />}
            {currentStep === 2 && <Step2Index />}
            {currentStep === 3 && <Step3Scope />}
            {currentStep === 4 && <Step4Results />}
          </main>
        </>
      )}

      <footer className="bg-surface border-t border-border py-4 px-6 text-center text-xs text-content-muted">
        <p>Comparador de Normativas vs Manuales Internos · interfaz mínima de prueba</p>
      </footer>
    </div>
  )
}
