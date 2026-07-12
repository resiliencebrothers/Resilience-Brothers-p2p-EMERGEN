import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as Sentry from "@sentry/react";
import "@/index.css";
import "@/i18n";
import App from "@/App";
import { registerSW } from "@/sw-register";
import { initSentry } from "@/sentry";

// No-op unless REACT_APP_SENTRY_DSN is configured at build time.
initSentry();

// Sentry ErrorBoundary is a no-op pass-through when DSN is missing.
const RootApp = process.env.REACT_APP_SENTRY_DSN
  ? Sentry.withErrorBoundary(App, {
      fallback: ({ error, resetError }) => (
        <div className="min-h-screen flex items-center justify-center bg-[#0a0a0a] text-white p-8">
          <div className="max-w-md text-center space-y-4">
            <h1 className="font-display text-2xl text-[#8B5CF6]">Algo salió mal</h1>
            <p className="text-neutral-400 text-sm">
              Hemos recibido el error y nuestro equipo ya está al tanto. Por favor recarga la página.
            </p>
            <button
              onClick={resetError}
              className="px-6 py-2 bg-[#8B5CF6] text-white font-medium hover:bg-[#fbc02d]"
              data-testid="error-boundary-reset"
            >
              Reintentar
            </button>
          </div>
        </div>
      ),
    })
  : App;

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      refetchOnWindowFocus: false,
    },
  },
});

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <RootApp />
    </QueryClientProvider>
  </React.StrictMode>,
);

registerSW();
