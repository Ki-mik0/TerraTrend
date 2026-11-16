import { lazy, Suspense } from "react";
import { BrowserRouter, Navigate, Routes, Route } from "react-router-dom";
import { ThemeProvider } from "./theme";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TopNav } from "./components/TopNav";
import { SessionSync } from "./components/SessionSync";
import { Backdrop, Skeleton } from "./components/ui";
import { Home } from "./pages/Home";

// Every page but the home page loads on first visit, so the map and charts do not slow the first screen.
const Explore = lazy(() => import("./pages/Explore").then((module) => ({ default: module.Explore })));
const Radar = lazy(() => import("./pages/Radar").then((module) => ({ default: module.Radar })));
const Compare = lazy(() => import("./pages/Compare").then((module) => ({ default: module.Compare })));
const Lab = lazy(() => import("./pages/Lab").then((module) => ({ default: module.Lab })));
const Journal = lazy(() => import("./pages/Journal").then((module) => ({ default: module.Journal })));
const Teacher = lazy(() => import("./pages/Teacher").then((module) => ({ default: module.Teacher })));
const Session = lazy(() => import("./pages/Session").then((module) => ({ default: module.Session })));
const CasePage = lazy(() => import("./pages/Case").then((module) => ({ default: module.CasePage })));
const Assistant = lazy(() => import("./pages/Assistant").then((module) => ({ default: module.Assistant })));
const Admin = lazy(() => import("./pages/Admin").then((module) => ({ default: module.Admin })));
const Join = lazy(() => import("./pages/Join").then((module) => ({ default: module.Join })));
const NotFound = lazy(() => import("./pages/NotFound").then((module) => ({ default: module.NotFound })));

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider defaultTheme="dark">
        <BrowserRouter>
          <SessionSync />
          <div className="relative min-h-screen flex flex-col bg-background text-foreground transition-colors duration-300">
            <Backdrop />
            <TopNav />
            <main className="relative z-0 flex-grow flex flex-col">
              <Suspense fallback={<PageFallback />}>
                <Routes>
                <Route path="/" element={<Home />} />
                <Route path="/explore" element={<Explore />} />
                <Route path="/radar" element={<Radar />} />
                <Route path="/compare" element={<Compare />} />
                <Route path="/learn" element={<Lab />} />
                <Route path="/journal" element={<Journal />} />
                <Route path="/teacher" element={<Teacher />} />
                <Route path="/session" element={<Session />} />
                <Route path="/case/:id" element={<CasePage />} />
                <Route path="/assistant" element={<Assistant />} />
                <Route path="/admin" element={<Admin />} />
                <Route path="/join/:token" element={<Join />} />
                <Route path="/lab" element={<Navigate to="/learn" replace />} />
                <Route path="*" element={<NotFound />} />
                </Routes>
              </Suspense>
            </main>
          </div>
        </BrowserRouter>
      </ThemeProvider>
    </QueryClientProvider>
  );
}

function PageFallback() {
  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-10 md:px-6" aria-busy="true">
      <Skeleton className="mb-4 h-10 w-72" />
      <Skeleton className="mb-8 h-5 w-[min(32rem,100%)]" />
      <Skeleton className="h-80 w-full" />
    </div>
  );
}
