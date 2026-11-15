import { BrowserRouter, Routes, Route } from "react-router-dom";
import { ThemeProvider } from "next-themes";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TopNav } from "./components/TopNav";
import { SessionSync } from "./components/SessionSync";
import { Backdrop } from "./components/ui";
import { Home } from "./pages/Home";
import { Explore } from "./pages/Explore";
import { Radar } from "./pages/Radar";
import { Compare } from "./pages/Compare";
import { Lab } from "./pages/Lab";
import { Journal } from "./pages/Journal";
import { Teacher } from "./pages/Teacher";
import { Session } from "./pages/Session";
import { CasePage } from "./pages/Case";
import { Assistant } from "./pages/Assistant";
import { Admin } from "./pages/Admin";
import { Join } from "./pages/Join";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider attribute="class" defaultTheme="dark" enableSystem={false}>
        <BrowserRouter>
          <SessionSync />
          <div className="relative min-h-screen flex flex-col bg-background text-foreground transition-colors duration-300">
            <Backdrop />
            <TopNav />
            <main className="relative z-0 flex-grow flex flex-col">
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
              </Routes>
            </main>
          </div>
        </BrowserRouter>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
