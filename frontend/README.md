# frontend/ — React + Vite + TypeScript + Tailwind

Interfaz **mínima de prueba** del pipeline: los 4 pasos (Documentos → Índice → Alcance → Resultados).
Sin login, visor PDF ni inspector de chunks; el código de esas piezas está en la rama del front Vue anterior.

```bash
npm install
npm run dev      # :5173, proxy /api → :8000 (VITE_BACKEND_URL para cambiarlo)
npm run build    # tsc + vite → dist/, que FastAPI sirve en /
```

Requiere el backend con `AUTH_ENABLED=false`. Estado en `src/store/useAppStore.ts` (Zustand);
llamadas HTTP en `src/api/client.ts`. Los colores salen de variables CSS (`src/index.css`).
