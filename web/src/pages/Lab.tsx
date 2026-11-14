import { useState } from "react";
import { Card, Chip } from "@heroui/react";
import { FlaskConical, Sliders, Cpu, CheckCircle, RefreshCw, Award } from "lucide-react";

export function Lab() {
    const [co2Level, setCo2Level] = useState(420);
    const [solarActivity, setSolarActivity] = useState(1361);
    const [aerosols, setAerosols] = useState(15);

    const baseTemp = 14.8;
    const tempAnomaly = Number(((co2Level - 410) * 0.015 + (solarActivity - 1361) * 0.005 - aerosols * 0.02).toFixed(2));
    const currentTemp = Number((baseTemp + tempAnomaly).toFixed(2));

    return (
        <div className="flex flex-col w-full min-h-[calc(100vh-73px)] p-6 md:p-10 max-w-7xl mx-auto">

            {/* Шапка страницы */}
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-8">
                <div>
                    <div className="flex items-center gap-2 mb-2">
                        <FlaskConical className="text-primary" size={26} />
                        <h1 className="text-3xl font-bold tracking-tight text-foreground">Climate Detective Lab</h1>
                    </div>
                    <p className="text-default-500 text-base max-w-2xl">
                        Interactive sandbox to test climate hypotheses. Adjust forcing factors and observe planetary response models in real time.
                    </p>
                </div>

                <Chip variant="soft" className="bg-primary/10 text-primary font-medium px-4 py-2">
                    Sandbox Mode Active
                </Chip>
            </div>

            {/* Основная сетка лабы */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">

                {/* Левая колонка: Управление факторами (Форсинги) */}
                <Card className="bg-default-50 border border-divider shadow-sm lg:col-span-1 p-2">
                    <Card.Content className="p-6 flex flex-col gap-6">
                        <div className="flex items-center gap-2 pb-4 border-b border-divider">
                            <Sliders size={20} className="text-primary" />
                            <h2 className="font-bold text-lg text-foreground">Climate Forcings</h2>
                        </div>

                        {/* Слайдер CO2 */}
                        <div className="flex flex-col gap-2">
                            <div className="flex justify-between text-sm">
                                <span className="font-medium text-default-600">Atmospheric CO₂</span>
                                <span className="font-bold text-primary">{co2Level} ppm</span>
                            </div>
                            <input
                                type="range"
                                min="300"
                                max="600"
                                value={co2Level}
                                onChange={(e) => setCo2Level(Number(e.target.value))}
                                className="w-full accent-primary cursor-pointer"
                            />
                            <span className="text-xs text-default-400">Baseline pre-industrial: ~280 ppm</span>
                        </div>

                        {/* Слайдер Солнечной активности */}
                        <div className="flex flex-col gap-2">
                            <div className="flex justify-between text-sm">
                                <span className="font-medium text-default-600">Solar Irradiance</span>
                                <span className="font-bold text-secondary">{solarActivity} W/m²</span>
                            </div>
                            <input
                                type="range"
                                min="1350"
                                max="1375"
                                value={solarActivity}
                                onChange={(e) => setSolarActivity(Number(e.target.value))}
                                className="w-full accent-secondary cursor-pointer"
                            />
                            <span className="text-xs text-default-400">11-year solar cycle variation</span>
                        </div>

                        {/* Слайдер Аэрозолей */}
                        <div className="flex flex-col gap-2">
                            <div className="flex justify-between text-sm">
                                <span className="font-medium text-default-600">Volcanic Aerosols</span>
                                <span className="font-bold text-warning">{aerosols} Index</span>
                            </div>
                            <input
                                type="range"
                                min="0"
                                max="50"
                                value={aerosols}
                                onChange={(e) => setAerosols(Number(e.target.value))}
                                className="w-full accent-warning cursor-pointer"
                            />
                            <span className="text-xs text-default-400">Cooling effect via light scattering</span>
                        </div>

                        <button
                            onClick={() => { setCo2Level(420); setSolarActivity(1361); setAerosols(15); }}
                            className="flex items-center justify-center gap-2 py-3 rounded-xl border border-divider text-sm font-medium text-default-600 hover:bg-default-100 transition-colors mt-2"
                        >
                            <RefreshCw size={16} /> Reset Parameters
                        </button>
                    </Card.Content>
                </Card>

                {/* Правая колонка: Визуализация модели и отклик планеты */}
                <div className="lg:col-span-2 flex flex-col gap-6">

                    {/* Главный дашборд отклика */}
                    <Card className="bg-default-50 border border-divider shadow-sm">
                        <Card.Content className="p-8 flex flex-col md:flex-row items-center justify-between gap-6">
                            <div>
                                <span className="text-xs font-semibold uppercase text-default-400 tracking-wider">Simulated Global State</span>
                                <h3 className="text-3xl font-bold text-foreground mt-1 mb-2">{currentTemp} °C</h3>
                                <p className="text-sm text-default-500">
                                    Global Surface Temperature Anomaly: <span className={tempAnomaly >= 0 ? "text-danger font-semibold" : "text-primary font-semibold"}>{tempAnomaly > 0 ? `+${tempAnomaly}` : tempAnomaly} °C</span> relative to baseline.
                                </p>
                            </div>

                            <div className="p-6 rounded-2xl bg-default-900 text-white flex flex-col items-center justify-center min-w-[200px] text-center">
                                <Cpu className="text-primary mb-2" size={28} />
                                <span className="text-xs text-default-400">Model Engine</span>
                                <span className="font-bold text-sm">Energy Balance v2.4</span>
                            </div>
                        </Card.Content>
                    </Card>

                    {/* Интерактивное задание (Detective Challenge) */}
                    <Card className="bg-gradient-to-r from-success/10 via-default-50 to-primary/10 border border-divider shadow-sm">
                        <Card.Content className="p-6 flex flex-col gap-4">
                            <div className="flex items-center gap-3">
                                <div className="w-10 h-10 rounded-xl bg-success/20 flex items-center justify-center text-success shrink-0">
                                    <Award size={22} />
                                </div>
                                <div>
                                    <h4 className="font-bold text-foreground">Mission Objective: Fingerprint Attribution</h4>
                                    <p className="text-sm text-default-500">Isolate the primary driver of recent warming by adjusting greenhouse gases while keeping solar activity constant.</p>
                                </div>
                            </div>

                            <div className="flex items-center justify-between p-4 rounded-xl bg-background border border-divider mt-2">
                                <div className="flex items-center gap-2">
                                    <CheckCircle size={18} className={co2Level > 500 ? "text-success" : "text-default-300"} />
                                    <span className="text-sm font-medium">Test high-emission scenario (&gt;500 ppm CO₂)</span>
                                </div>
                                <Chip variant="soft" className={co2Level > 500 ? "bg-success/20 text-success text-xs" : "bg-default-200 text-default-500 text-xs"}>
                                    {co2Level > 500 ? "Completed" : "Pending"}
                                </Chip>
                            </div>
                        </Card.Content>
                    </Card>

                </div>

            </div>

        </div>
    );
}