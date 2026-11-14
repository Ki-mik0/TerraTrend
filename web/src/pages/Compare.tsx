import { useState } from "react";
import { Card, Chip } from "@heroui/react";
import { GitCompare, Layers, ArrowLeftRight, CheckCircle2, TrendingUp, Sparkles } from "lucide-react";

export function Compare() {
    const [leftDataset, setLeftDataset] = useState("Land Surface Temperature (MODIS)");
    const [rightDataset, setRightDataset] = useState("Vegetation Index (NDVI)");

    return (
        <div className="flex flex-col w-full min-h-[calc(100vh-73px)] p-6 md:p-10 max-w-7xl mx-auto">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-8">
                <div>
                    <div className="flex items-center gap-2 mb-2">
                        <GitCompare className="text-primary" size={26} />
                        <h1 className="text-3xl font-bold tracking-tight text-foreground">Cross-Variable Comparison</h1>
                    </div>
                    <p className="text-default-500 text-base max-w-2xl">
                        Compare two environmental variables side-by-side to expose hidden teleconnections, lag effects, and causal relationships.
                    </p>
                </div>

                <Chip variant="soft" className="bg-primary/10 text-primary font-medium px-4 py-2">
                    Dual-Layer Mode Active
                </Chip>
            </div>

            <Card className="bg-default-50 border border-divider shadow-sm mb-8">
                <Card.Content className="p-6 grid grid-cols-1 md:grid-cols-[1fr,auto,1fr] gap-4 items-center">

                    <div className="flex flex-col gap-2">
                        <label className="text-xs font-semibold uppercase text-default-400">Primary Dataset (Left Layer)</label>
                        <select
                            value={leftDataset}
                            onChange={(e) => setLeftDataset(e.target.value)}
                            className="w-full p-3 rounded-xl border border-divider bg-background text-foreground text-sm focus:ring-2 focus:ring-primary outline-none"
                        >
                            <option>Land Surface Temperature (MODIS)</option>
                            <option>Precipitation (GPM IMERG)</option>
                            <option>Sea Surface Temperature</option>
                            <option>Atmospheric CO2 Concentration</option>
                        </select>
                    </div>

                    <div className="flex justify-center">
                        <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center text-primary">
                            <ArrowLeftRight size={20} />
                        </div>
                    </div>

                    <div className="flex flex-col gap-2">
                        <label className="text-xs font-semibold uppercase text-default-400">Secondary Dataset (Right Layer)</label>
                        <select
                            value={rightDataset}
                            onChange={(e) => setRightDataset(e.target.value)}
                            className="w-full p-3 rounded-xl border border-divider bg-background text-foreground text-sm focus:ring-2 focus:ring-primary outline-none"
                        >
                            <option>Vegetation Index (NDVI)</option>
                            <option>Soil Moisture (GLDAS)</option>
                            <option>Tropospheric NO2 Emissions</option>
                            <option>Sea Ice Concentration</option>
                        </select>
                    </div>

                </Card.Content>
            </Card>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">

                <Card className="bg-default-50 border border-divider shadow-sm overflow-hidden">
                    <div className="p-4 border-b border-divider bg-default-100/50 flex items-center justify-between">
            <span className="font-bold text-sm flex items-center gap-2">
              <Layers size={16} className="text-primary" /> {leftDataset}
            </span>
                        <Chip variant="soft" className="text-xs">Layer A</Chip>
                    </div>
                    <div className="h-72 bg-default-900 flex items-center justify-center relative overflow-hidden">
                        <div className="absolute inset-0 opacity-15 bg-[radial-gradient(#38bdf8_1px,transparent_1px)] [background-size:20px_20px]" />
                        <div className="text-center z-10 p-6">
                            <TrendingUp className="text-primary mx-auto mb-2" size={32} />
                            <p className="text-white font-medium text-sm">Spatial Distribution Map [Layer A]</p>
                            <p className="text-default-400 text-xs mt-1">Normalised anomaly index across selected region</p>
                        </div>
                    </div>
                </Card>

                <Card className="bg-default-50 border border-divider shadow-sm overflow-hidden">
                    <div className="p-4 border-b border-divider bg-default-100/50 flex items-center justify-between">
            <span className="font-bold text-sm flex items-center gap-2">
              <Layers size={16} className="text-secondary" /> {rightDataset}
            </span>
                        <Chip variant="soft" className="text-xs">Layer B</Chip>
                    </div>
                    <div className="h-72 bg-default-900 flex items-center justify-center relative overflow-hidden">
                        <div className="absolute inset-0 opacity-15 bg-[radial-gradient(#c084fc_1px,transparent_1px)] [background-size:20px_20px]" />
                        <div className="text-center z-10 p-6">
                            <TrendingUp className="text-secondary mx-auto mb-2" size={32} />
                            <p className="text-white font-medium text-sm">Spatial Distribution Map [Layer B]</p>
                            <p className="text-default-400 text-xs mt-1">Response variable index across selected region</p>
                        </div>
                    </div>
                </Card>

            </div>

            <Card className="bg-gradient-to-r from-primary/10 via-default-50 to-secondary/10 border border-divider shadow-sm">
                <Card.Content className="p-6 flex flex-col md:flex-row items-center justify-between gap-6">
                    <div className="flex items-center gap-4">
                        <div className="w-12 h-12 rounded-2xl bg-primary/20 flex items-center justify-center text-primary shrink-0">
                            <Sparkles size={24} />
                        </div>
                        <div>
                            <h3 className="font-bold text-lg text-foreground mb-1">Statistical Correlation Analysis</h3>
                            <p className="text-default-500 text-sm">
                                Evaluating Pearson coefficient between <span className="text-foreground font-medium">{leftDataset}</span> and <span className="text-foreground font-medium">{rightDataset}</span>.
                            </p>
                        </div>
                    </div>

                    <div className="flex items-center gap-6 shrink-0">
                        <div className="text-right">
                            <span className="text-xs text-default-400 block">Correlation (r)</span>
                            <span className="text-2xl font-bold text-primary">-0.82</span>
                        </div>
                        <div className="text-right border-l border-divider pl-6">
                            <span className="text-xs text-default-400 block">Significance</span>
                            <span className="text-2xl font-bold text-success flex items-center gap-1">
                <CheckCircle2 size={20} /> High
              </span>
                        </div>
                    </div>
                </Card.Content>
            </Card>

        </div>
    );
}