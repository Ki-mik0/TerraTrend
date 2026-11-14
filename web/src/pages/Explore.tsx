import { useState } from "react";
import { Button, Card, Chip } from "@heroui/react";
import { Play, Settings2, BarChart3, ShieldCheck, ThermometerSun, Map as MapIcon, Loader2, Globe } from "lucide-react";

export function Explore() {
    const [isAnalyzing, setIsAnalyzing] = useState(false);
    const [showResults, setShowResults] = useState(false);

    const handleAnalyze = () => {
        setIsAnalyzing(true);
        setTimeout(() => {
            setIsAnalyzing(false);
            setShowResults(true);
        }, 2000);
    };

    return (
        <div className="flex w-full h-[calc(100vh-73px)] overflow-hidden">

            {/* ЛЕВАЯ ПАНЕЛЬ */}
            <aside className="w-80 flex-shrink-0 border-r border-divider bg-background flex flex-col z-10 shadow-xl">
                <div className="p-4 border-b border-divider flex items-center gap-2">
                    <Settings2 className="text-primary" size={20} />
                    <h2 className="font-bold text-lg">Investigation Setup</h2>
                </div>

                <div className="p-4 flex flex-col gap-6 overflow-y-auto flex-grow">
                    <div className="flex flex-col gap-2">
                        <label className="text-sm font-medium text-default-600">Suspect Variable</label>
                        <select className="w-full p-2.5 rounded-lg border border-divider bg-default-100 text-foreground text-sm focus:ring-2 focus:ring-primary outline-none">
                            <option className="bg-background text-foreground">Land Surface Temperature (MODIS)</option>
                            <option className="bg-background text-foreground">Precipitation (GPM IMERG)</option>
                            <option className="bg-background text-foreground">Vegetation Index (NDVI)</option>
                            <option className="bg-background text-foreground">Soil Moisture (GLDAS)</option>
                        </select>
                    </div>

                    <div className="flex flex-col gap-2">
                        <label className="text-sm font-medium text-default-600">Crime Scene (Region)</label>
                        <select className="w-full p-2.5 rounded-lg border border-divider bg-default-100 text-foreground text-sm focus:ring-2 focus:ring-primary outline-none">
                            <option className="bg-background text-foreground">Global Scale</option>
                            <option className="bg-background text-foreground">Arctic Region</option>
                            <option className="bg-background text-foreground">Europe</option>
                            <option className="bg-background text-foreground">Custom Polygon (Draw)</option>
                        </select>
                    </div>

                    <div className="flex flex-col gap-2">
                        <label className="text-sm font-medium text-default-600">Timeframe</label>
                        <select className="w-full p-2.5 rounded-lg border border-divider bg-default-100 text-foreground text-sm focus:ring-2 focus:ring-primary outline-none">
                            <option className="bg-background text-foreground">2000 - 2023 (Full Record)</option>
                            <option className="bg-background text-foreground">2010 - 2023 (Recent Decade)</option>
                        </select>
                    </div>
                </div>

                <div className="p-4 border-t border-divider bg-default-50">
                    <Button
                        onClick={handleAnalyze}
                        isDisabled={isAnalyzing}
                        variant="primary"
                        className="w-full font-medium flex items-center justify-center gap-2 py-6 rounded-xl"
                    >
                        {isAnalyzing ? (
                            <><Loader2 size={18} className="animate-spin" /> Gathering Evidence...</>
                        ) : (
                            <><Play size={18} /> Run Analysis</>
                        )}
                    </Button>
                </div>
            </aside>

            {/* ЦЕНТРАЛЬНАЯ ЧАСТЬ */}
            <main className="flex-1 relative bg-default-900 flex items-center justify-center overflow-hidden">
                <div className="absolute inset-0 opacity-20 bg-[radial-gradient(#38bdf8_1px,transparent_1px)] [background-size:24px_24px]" />

                <div className="relative z-10 flex flex-col items-center text-center p-8 max-w-md">
                    <div className="w-20 h-20 rounded-full bg-primary/20 flex items-center justify-center mb-4 animate-pulse">
                        <Globe className="text-primary" size={40} />
                    </div>
                    <h3 className="text-xl font-bold text-foreground mb-2">Global Geospatial Canvas</h3>
                    <p className="text-default-400 text-sm mb-6">
                        Configure your suspect variable on the left panel and click <span className="text-primary font-semibold">Run Analysis</span> to generate the evidence protocol.
                    </p>
                </div>

                <div className="absolute top-4 left-4 z-10">
                    <Card className="bg-background/80 backdrop-blur-md border-none shadow-sm">
                        <Card.Content className="py-2 px-4 flex items-center gap-2">
                            <MapIcon size={16} className="text-default-500" />
                            <span className="text-sm font-medium">Map Layer: Trend Significance</span>
                        </Card.Content>
                    </Card>
                </div>
            </main>

            {/* ПРАВАЯ ПАНЕЛЬ */}
            <aside className={`w-96 flex-shrink-0 border-l border-divider bg-background flex flex-col z-10 shadow-xl transition-all duration-300 ${showResults ? 'translate-x-0' : 'translate-x-full hidden'}`}>
                <div className="p-4 border-b border-divider bg-primary/5 flex items-center gap-2">
                    <ShieldCheck className="text-primary" size={20} />
                    <h2 className="font-bold text-lg text-primary">Evidence Protocol</h2>
                </div>

                <div className="p-4 flex flex-col gap-4 overflow-y-auto flex-grow">
                    <Card className="bg-success/10 border-success/20 shadow-none">
                        <Card.Content className="p-4">
                            <h3 className="font-bold text-success flex items-center gap-2 mb-2">
                                ⚖️ Verdict: Proven Beyond Doubt
                            </h3>
                            <p className="text-sm text-default-600">
                                Strong evidence of increasing Land Surface Temperature. The trend remains robust even after isolating ENSO anomalies.
                            </p>
                        </Card.Content>
                    </Card>

                    <div className="flex flex-col gap-3 mt-2">
                        <h4 className="text-xs font-bold uppercase text-default-400 tracking-wider">Cross-Validation</h4>

                        <div className="flex items-center justify-between p-3 rounded-lg border border-divider bg-default-50">
                            <div className="flex items-center gap-2">
                                <BarChart3 size={16} className="text-primary" />
                                <span className="text-sm font-medium">Statistical Significance</span>
                            </div>
                            <Chip variant="soft" className="bg-success/20 text-success text-xs">p &lt; 0.01</Chip>
                        </div>

                        <div className="flex items-center justify-between p-3 rounded-lg border border-divider bg-default-50">
                            <div className="flex items-center gap-2">
                                <ThermometerSun size={16} className="text-warning" />
                                <span className="text-sm font-medium">Corroborating Sources</span>
                            </div>
                            <Chip variant="soft" className="bg-success/20 text-success text-xs">3 of 3</Chip>
                        </div>

                        <div className="flex items-center justify-between p-3 rounded-lg border border-divider bg-default-50">
                            <div className="flex flex-col">
                                <span className="text-sm font-medium">Confounding Factors</span>
                                <span className="text-xs text-default-500">ENSO, Volcanic Aerosols</span>
                            </div>
                            <Chip variant="soft" className="bg-success/20 text-success text-xs">Isolated</Chip>
                        </div>
                    </div>
                </div>
            </aside>

        </div>
    );
}