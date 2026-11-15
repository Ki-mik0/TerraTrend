import { useState, type ReactNode } from "react";
import { useMutation } from "@tanstack/react-query";
import { BookMarked, CheckCircle2, ChevronDown, Code2, Database, FileArchive, FileImage, FileSpreadsheet, FileText, Globe2, Image, Loader2, MapPinned, NotebookPen } from "lucide-react";
import { api } from "../api/client";
import { call, failureText } from "../api/http";
import { downloadFile } from "../api/sse";
import { useExpert, useTr } from "../i18n";
import { useStore } from "../store/useStore";
import { Notice, Panel, SectionTitle } from "./ui";

type Format = "pdf" | "html" | "png" | "zip" | "csv" | "geojson" | "ipynb" | "svg" | "nc" | "citation";

type Option = { format: Format; icon: ReactNode; title: [string, string]; text: [string, string]; ext: string };

/** The four files most people want: a report to read or print, a page, a picture to share, everything at once. */
const MAIN: Option[] = [
  { format: "pdf", icon: <FileText size={22} />, title: ["PDF-звіт", "PDF report"], text: ["Два аркуші: висновок, перевірки, графіки й цитування. Для друку й здачі.", "Two pages: the answer, the checks, charts and a citation. For printing and handing in."], ext: "pdf" },
  { format: "html", icon: <Globe2 size={22} />, title: ["Вебсторінка", "Web page"], text: ["Той самий звіт однією сторінкою — відкривається в будь-якому браузері.", "The same report as one page that opens in any browser."], ext: "html" },
  { format: "png", icon: <Image size={22} />, title: ["Картка для соцмереж", "Share card"], text: ["Картинка 1200×630 з вироком і графіком — для презентації чи допису.", "A 1200×630 picture with the verdict and a chart, for slides or a post."], ext: "png" },
  { format: "zip", icon: <FileArchive size={22} />, title: ["Усе одним архівом", "Everything as one archive"], text: ["Звіт, дані, графіки, ноутбук і цитування в одному ZIP.", "Report, data, charts, notebook and citation in one ZIP."], ext: "zip" },
];

/** Files for further work with the numbers. */
const DATA: Option[] = [
  { format: "csv", icon: <FileSpreadsheet size={18} />, title: ["Таблиця CSV", "CSV table"], text: ["Щомісячний ряд — відкривається в Excel.", "The monthly series — opens in Excel."], ext: "csv" },
  { format: "ipynb", icon: <NotebookPen size={18} />, title: ["Jupyter-ноутбук", "Jupyter notebook"], text: ["Готовий код, щоб повторити графік.", "Ready code to redraw the chart."], ext: "ipynb" },
  { format: "svg", icon: <FileImage size={18} />, title: ["Графік SVG", "SVG chart"], text: ["Векторний графік для слайдів.", "A vector chart for slides."], ext: "svg" },
  { format: "geojson", icon: <MapPinned size={18} />, title: ["GeoJSON", "GeoJSON"], text: ["Межі регіону з висновком — для QGIS і карт.", "The region outline with the result — for QGIS and maps."], ext: "geojson" },
  { format: "nc", icon: <Database size={18} />, title: ["NetCDF", "NetCDF"], text: ["Ряд у кліматичному форматі CF.", "The series in the CF climate format."], ext: "nc" },
  { format: "citation", icon: <BookMarked size={18} />, title: ["Цитування", "Citation"], text: ["Текст і BibTeX для списку джерел.", "Text and BibTeX for a reference list."], ext: "txt" },
];

export function ExportPanel({ caseId, ready, action }: { caseId: string; ready: boolean; action?: ReactNode }) {
  const tr = useTr();
  const expert = useExpert();
  const language = useStore((state) => state.language);
  const [more, setMore] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const exporter = useMutation({
    mutationFn: async (option: Option) => {
      const created = await call(api.POST("/api/v1/cases/{case_id}/export", { params: { path: { case_id: caseId } }, body: { format: option.format, language } }));
      const ready = created.status === "ready" ? created : await call(api.GET("/api/v1/exports/{export_id}", { params: { path: { export_id: created.id } } }));
      if (ready.status !== "ready") throw new Error(tr("Файл ще збирається, спробуй за мить.", "The file is still being built, try again shortly."));
      return downloadFile(`/api/v1/exports/${ready.id}/download`, ready.filename ?? `${caseId}.${option.ext}`);
    },
    onMutate: () => {
      setError(null);
      setSaved(null);
    },
    onSuccess: (name) => setSaved(name),
    onError: (reason) => setError(failureText(reason)),
  });
  const busy = exporter.isPending ? exporter.variables?.format : null;
  const showData = expert || more;
  const t = ([uk, en]: [string, string]) => tr(uk, en);

  return (
    <Panel>
      <SectionTitle icon={<FileText size={20} />} action={action}>
        {tr("Забери результат", "Take the result with you")}
      </SectionTitle>
      <p className="-mt-2 mb-4 text-sm text-muted">
        {tr("Обери, у якому вигляді зберегти розслідування. Файл одразу завантажиться.", "Choose how to save the investigation. The file downloads right away.")}
      </p>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {MAIN.map((option) => (
          <button
            key={option.format}
            type="button"
            disabled={!ready || exporter.isPending}
            onClick={() => exporter.mutate(option)}
            className="group relative flex flex-col gap-3 rounded-2xl border border-[var(--glass-border)] bg-surface/60 p-4 text-left transition hover:-translate-y-0.5 hover:border-accent/50 hover:shadow-md focus-visible:outline-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:translate-y-0"
          >
            <span className="flex items-center justify-between">
              <span className="bg-gradient-brand flex h-11 w-11 items-center justify-center rounded-xl text-white shadow-sm">
                {busy === option.format ? <Loader2 size={22} className="animate-spin" /> : option.icon}
              </span>
              <span className="rounded-md bg-default px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wide text-muted">.{option.ext}</span>
            </span>
            <span className="font-semibold text-foreground">{t(option.title)}</span>
            <span className="text-sm leading-snug text-muted">{t(option.text)}</span>
          </button>
        ))}
      </div>

      {!expert && (
        <button type="button" onClick={() => setMore((value) => !value)} className="mt-4 inline-flex items-center gap-1 text-sm font-medium text-accent hover:underline" aria-expanded={more}>
          <Code2 size={15} /> {more ? tr("Сховати файли для аналізу", "Hide files for analysis") : tr("Файли для подальшого аналізу", "Files for further analysis")}
          <ChevronDown size={15} className={more ? "rotate-180 transition" : "transition"} />
        </button>
      )}
      {showData && (
        <div className="mt-4">
          {expert && <h3 className="mb-2 text-sm font-semibold text-foreground">{tr("Дані та код", "Data and code")}</h3>}
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {DATA.map((option) => (
              <button
                key={option.format}
                type="button"
                disabled={!ready || exporter.isPending}
                onClick={() => exporter.mutate(option)}
                className="flex items-start gap-3 rounded-xl border border-[var(--glass-border)] p-3 text-left transition hover:border-accent/50 hover:bg-default/50 focus-visible:outline-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-60"
              >
                <span className="mt-0.5 text-accent">{busy === option.format ? <Loader2 size={18} className="animate-spin" /> : option.icon}</span>
                <span className="flex min-w-0 flex-col">
                  <span className="text-sm font-medium text-foreground">
                    {t(option.title)} <span className="font-mono text-[10px] uppercase text-muted">.{option.ext}</span>
                  </span>
                  <span className="text-xs text-muted">{t(option.text)}</span>
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

      {saved && (
        <p className="mt-4 flex items-center gap-2 text-sm text-success" role="status">
          <CheckCircle2 size={16} /> {tr("Завантажено:", "Downloaded:")} <code className="truncate">{saved}</code>
        </p>
      )}
      <Notice text={error} />
      {!ready && <p className="mt-3 text-xs text-muted">{tr("Експорт стане доступним, щойно справа завершиться.", "Export becomes available once the case is finished.")}</p>}
    </Panel>
  );
}
