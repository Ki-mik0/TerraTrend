import { useState } from "react";
import { Card, Chip } from "@heroui/react";
import { Users, Award, CheckCircle2, AlertCircle, Search, ChevronRight, BarChart2 } from "lucide-react";

const studentSubmissions = [
    {
        id: "st-01",
        name: "Alexandr Melenko",
        group: "Group 341(А)",
        activeCase: "One Process, Two Directions",
        score: "98 / 100",
        status: "Verified",
        submittedAt: "2 hours ago"
    },
    {
        id: "st-02",
        name: "Olena Nosova",
        group: "Group 341(А)",
        activeCase: "Arctic Amplification",
        score: "92 / 100",
        status: "Verified",
        submittedAt: "5 hours ago"
    },
    {
        id: "st-03",
        name: "Max Olenych",
        group: "Group 341(В)",
        activeCase: "The Urban Heat Island Spike",
        score: "Pending",
        status: "Needs Review",
        submittedAt: "1 day ago"
    }
];

export function Teacher() {
    const [searchQuery, setSearchQuery] = useState("");

    const filteredStudents = studentSubmissions.filter(student =>
        student.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        student.group.toLowerCase().includes(searchQuery.toLowerCase())
    );

    return (
        <div className="flex flex-col w-full min-h-[calc(100vh-73px)] p-6 md:p-10 max-w-7xl mx-auto">

            {/* Шапка страницы */}
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-8">
                <div>
                    <div className="flex items-center gap-2 mb-2">
                        <Users className="text-primary" size={26} />
                        <h1 className="text-3xl font-bold tracking-tight text-foreground">Teacher & Mentor Dashboard</h1>
                    </div>
                    <p className="text-default-500 text-base max-w-2xl">
                        Monitor student investigations, review submitted evidence protocols, and track analytical competencies.
                    </p>
                </div>

                <Chip variant="soft" className="bg-primary/10 text-primary font-medium px-4 py-2">
                    Admin / Mentor Mode
                </Chip>
            </div>

            {/* Карточки метрик */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
                <Card className="bg-default-50 border border-divider shadow-sm">
                    <Card.Content className="p-6 flex items-center gap-4">
                        <div className="w-12 h-12 rounded-2xl bg-primary/10 flex items-center justify-center text-primary shrink-0">
                            <Users size={24} />
                        </div>
                        <div>
                            <span className="text-xs text-default-400 block font-medium uppercase tracking-wider">Active Detectives</span>
                            <span className="text-2xl font-bold text-foreground">34 Students</span>
                        </div>
                    </Card.Content>
                </Card>

                <Card className="bg-default-50 border border-divider shadow-sm">
                    <Card.Content className="p-6 flex items-center gap-4">
                        <div className="w-12 h-12 rounded-2xl bg-success/10 flex items-center justify-center text-success shrink-0">
                            <Award size={24} />
                        </div>
                        <div>
                            <span className="text-xs text-default-400 block font-medium uppercase tracking-wider">Average Score</span>
                            <span className="text-2xl font-bold text-foreground">94.5 / 100</span>
                        </div>
                    </Card.Content>
                </Card>

                <Card className="bg-default-50 border border-divider shadow-sm">
                    <Card.Content className="p-6 flex items-center gap-4">
                        <div className="w-12 h-12 rounded-2xl bg-warning/10 flex items-center justify-center text-warning shrink-0">
                            <BarChart2 size={24} />
                        </div>
                        <div>
                            <span className="text-xs text-default-400 block font-medium uppercase tracking-wider">Completion Rate</span>
                            <span className="text-2xl font-bold text-foreground">88% Solved</span>
                        </div>
                    </Card.Content>
                </Card>
            </div>

            {/* Поиск и таблица студентов */}
            <Card className="bg-default-50 border border-divider shadow-sm mb-12">
                <div className="p-6 border-b border-divider flex flex-col sm:flex-row items-center justify-between gap-4">
                    <h3 className="font-bold text-lg text-foreground">Student Submissions & Progress</h3>

                    <div className="relative w-full sm:w-72">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-default-400" size={16} />
                        <input
                            type="text"
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                            placeholder="Search student or group..."
                            className="w-full pl-9 pr-4 py-2 rounded-xl border border-divider bg-background text-foreground text-sm focus:ring-2 focus:ring-primary outline-none"
                        />
                    </div>
                </div>

                <div className="overflow-x-auto">
                    <table className="w-full text-left border-collapse">
                        <thead>
                        <tr className="border-b border-divider text-xs text-default-400 uppercase bg-default-100/50">
                            <th className="p-4 font-semibold">Student Name</th>
                            <th className="p-4 font-semibold">Active Investigation</th>
                            <th className="p-4 font-semibold">Score</th>
                            <th className="p-4 font-semibold">Status</th>
                            <th className="p-4 font-semibold">Submitted</th>
                            <th className="p-4 text-right font-semibold">Actions</th>
                        </tr>
                        </thead>
                        <tbody className="divide-y divide-divider text-sm">
                        {filteredStudents.map((student) => (
                            <tr key={student.id} className="hover:bg-default-100/40 transition-colors">
                                <td className="p-4 font-medium text-foreground">
                                    {student.name}
                                    <span className="block text-xs text-default-400">{student.group}</span>
                                </td>
                                <td className="p-4 text-default-600">{student.activeCase}</td>
                                <td className="p-4 font-bold text-foreground">{student.score}</td>
                                <td className="p-4">
                                    <Chip variant="soft" className={student.status === 'Verified' ? 'bg-success/20 text-success text-xs' : 'bg-warning/20 text-warning text-xs'}>
                                        {student.status === 'Verified' ? <CheckCircle2 size={12} className="inline mr-1" /> : <AlertCircle size={12} className="inline mr-1" />}
                                        {student.status}
                                    </Chip>
                                </td>
                                <td className="p-4 text-default-400 text-xs">{student.submittedAt}</td>
                                <td className="p-4 text-right">
                                    <button className="p-2 rounded-lg hover:bg-default-200/60 transition-colors text-primary inline-flex items-center gap-1 font-medium text-xs">
                                        Review <ChevronRight size={14} />
                                    </button>
                                </td>
                            </tr>
                        ))}
                        </tbody>
                    </table>
                </div>
            </Card>

        </div>
    );
}