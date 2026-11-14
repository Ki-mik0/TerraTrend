import { useNavigate } from "react-router-dom";
import { Button, Card, Chip } from "@heroui/react";
import { ArrowRight, Activity, Globe, Zap } from "lucide-react";

const demoCases = [
    {
        id: "stratosphere",
        title: "One Process, Two Directions",
        description: "Troposphere warms, stratosphere cools. A classic fingerprint of greenhouse gases.",
        tag: "Atmosphere",
        image: "https://images.unsplash.com/photo-1536244636800-a3f74db0f3cf?q=80&w=600&auto=format&fit=crop"
    },
    {
        id: "urban-heat",
        title: "The Urban Heat Island",
        description: "Does the city warm faster than its suburbs? Comparing MODIS Land Surface Temp at night.",
        tag: "Cities",
        image: "https://images.unsplash.com/photo-1477959858617-67f85cf4f1df?q=80&w=600&auto=format&fit=crop"
    },
    {
        id: "arctic-amplification",
        title: "Arctic Amplification",
        description: "The strongest evidence of warming. All corroborating sources agree on the trend.",
        tag: "Cryosphere",
        image: "https://images.unsplash.com/photo-1542332213-9b5a5a3fad35?q=80&w=600&auto=format&fit=crop"
    },
    {
        id: "enso-alibi",
        title: "Is it just El Niño?",
        description: "How the 'Alibi' tool filters out natural variability to reveal the true underlying trend.",
        tag: "Oceans",
        image: "https://images.unsplash.com/photo-1582967788606-a171c1080cb0?q=80&w=600&auto=format&fit=crop"
    }
];

export function Home() {
    const navigate = useNavigate();

    return (
        <div className="flex flex-col w-full">
            <section className="relative flex flex-col items-center justify-center pt-24 pb-32 px-6 text-center overflow-hidden">
                <div className="absolute top-0 -z-10 w-full h-full overflow-hidden opacity-30 dark:opacity-20 pointer-events-none">
                    <div className="absolute -top-[10%] -left-[10%] w-[40%] h-[50%] rounded-full bg-blue-500/30 blur-[120px]" />
                    <div className="absolute top-[20%] -right-[10%] w-[50%] h-[60%] rounded-full bg-emerald-500/20 blur-[120px]" />
                </div>

                <Chip variant="soft" className="mb-6 font-medium text-emerald-500 bg-emerald-500/10">
                    NASA Space Apps Challenge 2024
                </Chip>

                <h1 className="text-5xl md:text-7xl font-bold tracking-tight mb-6 max-w-4xl text-foreground">
                    TerraTrend <span className="bg-gradient-to-r from-blue-500 to-emerald-500 bg-clip-text text-transparent">Detective</span>
                </h1>

                <p className="text-xl md:text-2xl text-default-500 max-w-3xl mb-10 leading-relaxed">
                    Investigate significant changes in the Earth's interconnected system.
                    Gather evidence, cross-validate sources, and expose the true climate trends.
                </p>

                <div className="flex flex-col sm:flex-row gap-4">
                    <Button
                        onClick={() => navigate('/explore')}
                        variant="primary"
                        className="font-medium px-8 py-6 text-lg flex items-center gap-2 shadow-lg shadow-primary/30 rounded-xl"
                    >
                        Start Investigation <ArrowRight size={18} />
                    </Button>
                    <Button
                        onClick={() => navigate('/radar')}
                        variant="outline"
                        className="font-medium px-8 py-6 text-lg flex items-center gap-2 rounded-xl"
                    >
                        <Activity size={18} /> Open Trend Radar
                    </Button>
                </div>
            </section>

            <section className="px-6 py-16 max-w-7xl mx-auto w-full">
                <div className="flex items-center gap-3 mb-8">
                    <h2 className="text-3xl font-bold text-foreground">Featured Case Studies</h2>
                </div>

                <p className="text-default-500 mb-8 max-w-2xl text-lg">
                    Dive into pre-configured investigations. These cases demonstrate how to find opposing trends, test for robustness, and verify environmental alibis.
                </p>

                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                    {demoCases.map((demo) => (
                        <Card
                            key={demo.id}
                            className="w-full bg-default-50 hover:bg-default-100 transition-colors cursor-pointer border-none overflow-hidden"
                            onClick={() => navigate(`/explore?case=${demo.id}`)}
                        >
                            <Card.Header className="absolute z-10 top-1 flex-col items-start p-0">
                                <Chip variant="soft" className="m-3 text-xs">
                                    {demo.tag}
                                </Chip>
                            </Card.Header>

                            <img
                                alt={demo.title}
                                className="z-0 w-full h-[200px] object-cover"
                                src={demo.image}
                            />

                            <Card.Content className="pt-4 pb-2 px-4">
                                <h3 className="font-bold text-lg mb-2 leading-tight">{demo.title}</h3>
                                <p className="text-default-500 text-sm line-clamp-3">
                                    {demo.description}
                                </p>
                            </Card.Content>
                            <Card.Footer className="px-4 pb-4 pt-0 justify-end">
                <span className="text-primary text-sm font-medium flex items-center gap-1">
                  Examine Case <ArrowRight size={14} />
                </span>
                            </Card.Footer>
                        </Card>
                    ))}
                </div>
            </section>

            <section className="px-6 py-16 mb-20 max-w-7xl mx-auto w-full">
                <Card className="w-full bg-gradient-to-br from-default-100 to-default-50 border border-divider shadow-sm">
                    <Card.Content className="p-8 md:p-12 flex flex-col md:flex-row items-center justify-between gap-8">
                        <div className="max-w-xl text-left">
                            <div className="flex items-center gap-3 mb-4">
                                <Zap className="text-warning" size={24} />
                                <h2 className="text-2xl font-bold">Live Anomaly Patrol</h2>
                            </div>
                            <p className="text-default-600 text-lg mb-6">
                                Our system constantly scans thousands of region-variable pairs to find the most significant accelerating and opposing trends worldwide.
                            </p>
                            <Button onClick={() => navigate('/radar')} variant="secondary" className="font-medium px-6 flex items-center gap-2">
                                View Global Pulse <Activity size={16} />
                            </Button>
                        </div>

                        <div className="relative w-48 h-48 rounded-full border-2 border-primary/20 flex items-center justify-center shrink-0">
                            <div className="absolute w-32 h-32 rounded-full border-2 border-primary/40 animate-ping" style={{ animationDuration: '3s' }} />
                            <div className="absolute w-16 h-16 rounded-full bg-primary/20 flex items-center justify-center">
                                <Globe className="text-primary" size={32} />
                            </div>
                            <div className="absolute top-8 right-10 w-3 h-3 rounded-full bg-danger shadow-[0_0_10px_rgba(243,18,96,0.8)]" />
                            <div className="absolute bottom-12 left-8 w-2 h-2 rounded-full bg-warning shadow-[0_0_10px_rgba(245,165,36,0.8)]" />
                        </div>
                    </Card.Content>
                </Card>
            </section>
        </div>
    );
}