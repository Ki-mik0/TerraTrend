import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { ThemeProvider } from 'next-themes';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TopNav } from './components/TopNav';
import { Home } from './pages/Home';
import { Explore } from './pages/Explore';
import { Radar } from './pages/Radar';
import { Compare } from './pages/Compare';
import { Lab } from './pages/Lab';
import { Journal } from './pages/Journal';
import { Teacher } from './pages/Teacher';

const queryClient = new QueryClient();

export default function App() {
    return (
        <QueryClientProvider client={queryClient}>
            <ThemeProvider attribute="class" defaultTheme="system">
                <BrowserRouter>
                    <div className="min-h-screen flex flex-col bg-background text-foreground transition-colors duration-300">
                        <TopNav />
                        <main className="flex-grow flex flex-col">
                            <Routes>
                                <Route path="/" element={<Home />} />
                                <Route path="/explore" element={<Explore />} />
                                <Route path="/radar" element={<Radar />} />
                                <Route path="/compare" element={<Compare />} />
                                <Route path="/learn" element={<Lab />} />
                                <Route path="/journal" element={<Journal />} />
                                <Route path="/teacher" element={<Teacher />} />
                            </Routes>
                        </main>
                    </div>
                </BrowserRouter>
            </ThemeProvider>
        </QueryClientProvider>
    );
}