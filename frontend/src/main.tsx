import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, StrictMode, Suspense } from "react";
import { createRoot } from "react-dom/client";
import { HashRouter, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { Spinner, ToastProvider } from "./components/ui";
import { ThemeProvider } from "./lib/theme";
import Home from "./pages/Home";
import "./styles.css";

const NewProject = lazy(() => import("./pages/NewProject"));
const Project = lazy(() => import("./pages/Project"));
const Projects = lazy(() => import("./pages/Projects"));
const Templates = lazy(() => import("./pages/Templates"));
const TemplateDetail = lazy(() => import("./pages/TemplateDetail"));
const System = lazy(() => import("./pages/System"));

const qc = new QueryClient({
  defaultOptions: { queries: { staleTime: 10_000, refetchOnWindowFocus: false, retry: 1 } },
});

const Fallback = () => (
  <div className="grid min-h-[60vh] place-items-center"><Spinner size={28} className="text-accent" /></div>
);

// HashRouter: мини-приложение VK открывается с query-параметрами запуска — хеш-маршруты им не мешают.
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <ToastProvider>
          <HashRouter>
            <Suspense fallback={<Fallback />}>
              <Routes>
                <Route element={<AppShell />}>
                  <Route index element={<Home />} />
                  <Route path="new" element={<NewProject />} />
                  <Route path="project/:id" element={<Project />} />
                  <Route path="projects" element={<Projects />} />
                  <Route path="templates" element={<Templates />} />
                  <Route path="templates/:id" element={<TemplateDetail />} />
                  <Route path="system" element={<System />} />
                  <Route path="*" element={<Home />} />
                </Route>
              </Routes>
            </Suspense>
          </HashRouter>
        </ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>
  </StrictMode>,
);
