import { Check, ChevronRight } from 'lucide-react'
import { useAppStore } from '@/store/useAppStore'

const STEPS = [
  { number: 1, title: '1. Documentos', desc: 'Carga y tabulación Docling' },
  { number: 2, title: '2. Índice Semántico', desc: 'FAISS + Sub-chunking' },
  { number: 3, title: '3. Alcance & Comparación', desc: 'Doble vía N:N' },
  { number: 4, title: '4. Resultados & Auditoría', desc: 'Papel de Trabajo Excel' },
]

export default function Stepper() {
  const current = useAppStore((s) => s.currentStep)
  const set = useAppStore((s) => s.set)

  return (
    <div className="bg-surface border-b border-border py-3 px-4 shadow-sm">
      <div className="max-w-7xl mx-auto flex items-center justify-between overflow-x-auto no-scrollbar">
        {STEPS.map((step, idx) => {
          const activo = current === step.number
          const hecho = current > step.number
          return (
            <div
              key={step.number}
              // Solo se navega hacia atrás o al paso actual.
              onClick={() => step.number <= current && set({ currentStep: step.number })}
              className={`flex items-center space-x-2 sm:space-x-3 py-1 px-2 rounded-lg transition cursor-pointer ${
                activo
                  ? 'bg-primary-light text-primary font-semibold'
                  : hecho
                    ? 'text-slate-700 hover:bg-slate-50'
                    : 'text-slate-400 opacity-80 cursor-default'
              }`}
            >
              <div
                className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold transition ${
                  activo ? 'bg-primary text-white shadow' : hecho ? 'bg-emerald-500 text-white' : 'bg-slate-200 text-slate-500'
                }`}
              >
                {hecho ? <Check className="w-4 h-4" /> : <span>{step.number}</span>}
              </div>
              <div className="flex flex-col text-left">
                <span className="text-xs sm:text-sm whitespace-nowrap">{step.title}</span>
                <span className="text-[10px] text-content-muted hidden md:inline">{step.desc}</span>
              </div>
              {idx < STEPS.length - 1 && <ChevronRight className="w-4 h-4 text-slate-300 ml-2 hidden sm:block" />}
            </div>
          )
        })}
      </div>
    </div>
  )
}
