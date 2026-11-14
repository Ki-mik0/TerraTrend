import { useState } from "react";
import { Button, Card, Chip } from "@heroui/react";
import { BookOpen, CheckCircle2, Clock, FileText, Plus, Search } from "lucide-react";

const investigativeCases = [
    {
        id: "case-01",
        title: "One Process, Two Directions (Troposphere vs Stratosphere)",
        category: "Atmosphere",
        date: "2024-10-02",
        status: "Solved",
        evidenceCount: 4,
        summary: "Successfully isolated greenhouse gas fingerprint by proving simultaneous tropospheric warming and stratospheric cooling."
    },
    {
        id: "case-02",
        title: "The Urban Heat Island Spike in Milan",
        category: "Cities",
        date: "2024-10-01",
        status: "In Progress",
        evidenceCount: 2,
        summary: "Analyzing MODIS night-time land surface temperature anomalies relative to surrounding rural baseline."
    },
    {
        id: "case-03",
        title: "Arctic Amplification and Sea Ice Minimum",
        category: "Cryosphere",
        date: "2024-09-28",
        status: "Solved",
        evidenceCount: 5,
        summary: "Corroborated ice concentration records across 3 independent satellite sensors with p < 0.001 significance."
    }
];

export function Journal() {
    const [filter, setFilter] = useState("All");

    const filteredCases = filter === "All"
        ? investigativeCases
        : investigativeCases.filter(item => item.status === filter);

    return (
        <div className="flex flex-col w-full min-h-[calc(100vh-73px)] p-6 md:p-10 max-w-7xl mx-auto">

            {/* Шапка страницы */}
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-8">
                <div>
                    <div className="flex items-center gap-2 mb-2">
                        <BookOpen className="text-primary" size={26} />
                        <h1 className="text-3xl font-bold tracking-tight text-foreground">Investigative Field Journal</h1>
                    </div>
                    <p className="text-default-500 text-base max-w-2xl">
                        Chronicle of climate investigations, saved evidence protocols, and verified forensic reports.
                    </p>
                </div>

                <Button
                    variant="primary"
                    className="font-medium px-6 py-3 rounded-xl flex items-center gap-2"
                >
                    <Plus size={18} /> New Investigation Log
                </Button>
            </div>

            {/* Панель фильтрации */}
            <div className="flex flex-col sm:flex-row items-center justify-between gap-4 mb-6">
                <div className="flex items-center gap-2 w-full sm:w-auto">
                    {["All", "Solved", "In Progress"].map((tab) => (
                        <Button
                            key={tab}
                            onClick={() => setFilter(tab)}
                            variant={filter === tab ? "primary" : "outline"}
                            className="text-sm font-medium rounded-xl px-4"
                        >
                            {tab}
                        </Button>
                    ))}
                </div>

                <div className="relative w-full sm:w-72">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-default-400" size={16} />
                    <input
                        type="text"
                        placeholder="Search log entries..."
                        className="w-full pl-9 pr-4 py-2.5 rounded-xl border border-divider bg-background text-foreground text-sm focus:ring-2 focus:ring-primary outline-none"
                    />
                </div>
            </div>

            {/* Список записей журнала */}
            <div className="flex flex-col gap-4 mb-12">
                {filteredCases.map((item) => (
                    <Card key={item.id} className="bg-default-50 hover:bg-default-100 transition-all border border-divider shadow-sm">
                        <Card.Content className="p-6 flex flex-col md:flex-row items-start md:items-center justify-between gap-6">

                            <div className="flex items-start gap-4">
                                <div className={`p-3 rounded-2xl shrink-0 ${item.status === 'Solved' ? 'bg-success/10 text-success' : 'bg-warning/10 text-warning'}`}>
                                    {item.status === 'Solved' ? <CheckCircle2 size={24} /> : <Clock size={24} />}
                                </div>

                                <div className="flex flex-col gap-1">
                                    <div className="flex items-center gap-3">
                                        <span className="text-xs font-semibold text-default-400 uppercase tracking-wider">{item.category}</span>
                                        <span className="text-xs text-default-400">• {item.date}</span>
                                    </div>
                                    <h3 className="font-bold text-lg text-foreground">{item.title}</h3>
                                    <p className="text-sm text-default-500 max-w-3xl">{item.summary}</p>
                                </div>
                            </div>

                            <div className="flex items-center gap-4 shrink-0 w-full md:w-auto justify-between md:justify-end border-t md:border-t-0 pt-4 md:pt-0 border-divider">
                                <div className="flex flex-col items-start md:items-end">
                                    <span className="text-xs text-default-400">Evidence Files</span>
                                    <span className="text-sm font-bold text-foreground flex items-center gap-1">
                    <FileText size={14} className="text-primary" /> {item.evidenceCount} protocols
                  </span>
                                </div>

                                <Chip variant="soft" className={item.status === 'Solved' ? 'bg-success/20 text-success text-xs font-medium' : 'bg-warning/20 text-warning text-xs font-medium'}>
                                    {item.status}
                                </Chip>
                            </div>

                        </Card.Content>
                    </Card>
                ))}
            </div>

        </div>
    );
}