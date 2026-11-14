import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button, Card, Chip } from "@heroui/react";
import { Activity, ArrowRight, Flame, ShieldAlert, Sparkles, TrendingUp, Wind, Waves } from "lucide-react";

// База данных найденных автоматических аномалий
const radarAnomalies = [
    {
        id: "arctic-ice-loss",
        title: "Accelerating Sea Ice Minimum",
        region: "Barents Sea, Arctic",
        variable: "Sea Ice Concentration",
        trend: "-14.2% per decade",
        significance: "p < 0.001",
        category: "Cryosphere",
        severity: "critical",
        icon: Wind
    },
    {
        id: "urban-heat-milan",
        title: "Nocturnal Heat Island Spike",
        region: "Milan Metropolitan Area, Italy",
        variable: "Land Surface Temp (Night)",
        trend: "+0.8°C / decade",
        significance: "p < 0.01",
        category: "Cities",
        severity: "warning",
        icon: Flame
    },
    {
        id: "amazon-drought",
        title: "Prolonged Soil Moisture Deficit",
        region: "Southern Amazon Basin",
        variable: "Root Zone Soil Moisture",
        trend: "-3.5 SD anomaly",
        significance: "p < 0.001",
        category: "Ecosystems",
        severity: "critical",
        icon: ShieldAlert
    },
    {
        id: "north-atlantic-sst",
        title: "Unprecedented Surface Warming",
        region: "Subpolar North Atlantic",
        variable: "Sea Surface Temperature",
        trend: "+1.2°C above baseline",
        significance: "p < 0.0001",
        category: "Oceans",
        severity: "critical",
        icon: Waves
    }
];

export function Radar() {
    const navigate = useNavigate();
    const [selectedCategory, setSelectedCategory] = useState("All");

    const categories = ["All", "Cryosphere", "Cities", "Ecosystems", "Oceans"];

    const filteredAnomalies = selectedCategory === "All"
        ? radarAnomalies
        : radarAnomalies.filter(item => item.category === selectedCategory);

    return (
        <div className="flex flex-col w-full min-h-[calc(100vh-73px)] p-6 md:p-10 max-w-7xl mx-auto">

            {/* Шапка страницы */}
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-8">
                <div>
                    <div className="flex items-center gap-2 mb-2">
                        <Activity className="text-primary animate-pulse" size={24} />
                        <h1 className="text-3xl font-bold tracking-tight text-foreground">Global Trend Radar</h1>
                    </div>
                    <p className="text-default-500 text-base max-w-2xl">
                        Automated anomaly patrol scanning thousands of Earth observation pairs. Detecting high-significance accelerations and unexpected opposing trends worldwide.
                    </p>
                </div>

                {/* Статус сканирования */}
                <Card className="bg-primary/10 border border-primary/20 shadow-none shrink-0">
                    <Card.Content className="py-3 px-4 flex items-center gap-3">
                        <div className="w-3 h-3 rounded-full bg-success animate-ping" />
                        <div className="flex flex-col">
                            <span className="text-xs font-bold uppercase text-primary tracking-wider">Radar Status</span>
                            <span className="text-xs text-default-600">Active Scan • 4,210 pairs monitored</span>
                        </div>
                    </Card.Content>
                </Card>
            </div>

            {/* Фильтры по категориям */}
            <div className="flex items-center gap-2 overflow-x-auto pb-4 mb-6">
                {categories.map((cat) => (
                    <Button
                        key={cat}
                        onClick={() => setSelectedCategory(cat)}
                        variant={selectedCategory === cat ? "primary" : "outline"}
                        className="text-sm font-medium rounded-xl px-4"
                    >
                        {cat}
                    </Button>
                ))}
            </div>

            {/* Список найденных аномалий (сетка) */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-12">
                {filteredAnomalies.map((item) => {
                    const IconComponent = item.icon;
                    return (
                        <Card
                            key={item.id}
                            className="bg-default-50 hover:bg-default-100 transition-all border border-divider shadow-sm p-2 flex flex-col justify-between"
                        >
                            <Card.Content className="p-5 flex flex-col gap-4">
                                <div className="flex items-start justify-between gap-3">
                                    <div className="flex items-center gap-3">
                                        <div className={`p-3 rounded-xl ${item.severity === 'critical' ? 'bg-danger/10 text-danger' : 'bg-warning/10 text-warning'}`}>
                                            <IconComponent size={22} />
                                        </div>
                                        <div>
                                            <span className="text-xs font-semibold text-default-400 uppercase tracking-wider">{item.region}</span>
                                            <h3 className="font-bold text-lg text-foreground leading-tight">{item.title}</h3>
                                        </div>
                                    </div>
                                    <Chip variant="soft" className="text-xs bg-default-200/50">
                                        {item.category}
                                    </Chip>
                                </div>

                                <div className="grid grid-cols-2 gap-3 py-3 border-y border-divider">
                                    <div>
                                        <span className="text-xs text-default-400 block mb-1">Variable</span>
                                        <span className="text-sm font-medium text-foreground">{item.variable}</span>
                                    </div>
                                    <div>
                                        <span className="text-xs text-default-400 block mb-1">Detected Trend</span>
                                        <span className="text-sm font-bold text-primary flex items-center gap-1">
                      <TrendingUp size={14} /> {item.trend}
                    </span>
                                    </div>
                                </div>

                                <div className="flex items-center justify-between pt-1">
                                    <div className="flex items-center gap-2">
                                        <Sparkles size={14} className="text-success" />
                                        <span className="text-xs font-medium text-success">Significance: {item.significance}</span>
                                    </div>

                                    <Button
                                        onClick={() => navigate(`/explore?anomaly=${item.id}`)}
                                        variant="outline"
                                        className="text-xs font-medium px-4 py-2 h-auto flex items-center gap-1.5"
                                    >
                                        Investigate <ArrowRight size={14} />
                                    </Button>
                                </div>
                            </Card.Content>
                        </Card>
                    );
                })}
            </div>

        </div>
    );
}