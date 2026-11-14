import { Link, useLocation } from "react-router-dom";
import { ThemeSwitcher } from "./ThemeSwitcher";

export function TopNav() {
    const location = useLocation();

    const tabs = [
        { path: '/', label: 'Home' },
        { path: '/explore', label: 'Explore' },
        { path: '/radar', label: 'Trend Radar' },
        { path: '/compare', label: 'Compare' },
        { path: '/learn', label: 'Lab' },
        { path: '/journal', label: 'Journal' },
        { path: '/teacher', label: 'Teacher' },
    ];

    return (
        <nav className="sticky top-0 z-50 flex w-full items-center justify-between px-6 py-3 bg-background/70 backdrop-blur-lg backdrop-saturate-150 border-b border-divider">
            <div className="flex items-center gap-8">
                <Link to="/" className="font-bold text-2xl tracking-wide text-foreground">
                    TerraTrend
                </Link>

                <ul className="flex items-center gap-1">
                    {tabs.map((tab) => {
                        const isActive = location.pathname === tab.path;
                        return (
                            <li key={tab.path}>
                                <Link
                                    to={tab.path}
                                    className={`px-3 py-2 text-sm rounded-medium transition-colors ${
                                        isActive
                                            ? "bg-primary/20 text-primary font-medium"
                                            : "text-default-600 hover:bg-default-100 hover:text-foreground"
                                    }`}
                                >
                                    {tab.label}
                                </Link>
                            </li>
                        );
                    })}
                </ul>
            </div>

            <div className="flex items-center gap-4">
                <ThemeSwitcher />
            </div>
        </nav>
    );
}