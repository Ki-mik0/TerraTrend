/**
 * The design kit of TerraTrend. Colours come only from HeroUI 3 tokens (background, surface,
 * foreground, muted, border, accent, success, warning, danger) and the brand gradient in
 * index.css, so the dark and the light theme both work.
 */
import { useId, useState } from "react";
import type { ComponentProps, ElementType, ReactNode } from "react";
import { AlertTriangle, CheckCircle2, ChevronDown, CircleHelp, Info, XCircle } from "lucide-react";

import type { Check } from "../explain";
import { useTr, verdictLabel } from "../i18n";
import { useStore } from "../store/useStore";
import { TERMS, VERDICT_MEANING, type TermId } from "../terms";

function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

/** Soft glow behind every screen, the same mood as the landing hero. */
export function Backdrop() {
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
      <div
        className="absolute -top-40 -left-32 h-[520px] w-[620px] rounded-full bg-brand-from blur-[140px]"
        style={{ opacity: "var(--glow-opacity)" }}
      />
      <div
        className="absolute top-1/3 -right-40 h-[560px] w-[640px] rounded-full bg-brand-to blur-[160px]"
        style={{ opacity: "calc(var(--glow-opacity) * 0.7)" }}
      />
    </div>
  );
}

export function Page({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  return (
    <div className={cx("mx-auto w-full px-4 sm:px-6 lg:px-10 py-8 md:py-10", wide ? "max-w-[1600px]" : "max-w-7xl")}>
      {children}
    </div>
  );
}

export function PageHeader({
  icon,
  title,
  subtitle,
  eyebrow,
  actions,
}: {
  icon?: ReactNode;
  title: ReactNode;
  subtitle?: ReactNode;
  eyebrow?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="mb-8 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
      <div className="flex items-start gap-4 min-w-0">
        {icon && (
          <div className="bg-gradient-brand flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl text-white shadow-lg shadow-brand-from/25">
            {icon}
          </div>
        )}
        <div className="min-w-0">
          {eyebrow && <p className="mb-1 text-xs font-semibold uppercase tracking-widest text-muted">{eyebrow}</p>}
          <h1 className="text-3xl md:text-4xl font-bold tracking-tight text-foreground">{title}</h1>
          {subtitle && <p className="mt-2 max-w-3xl text-base text-muted">{subtitle}</p>}
        </div>
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

type PanelProps<T extends ElementType> = {
  as?: T;
  interactive?: boolean;
  padded?: boolean;
  className?: string;
  children?: ReactNode;
} & Omit<ComponentProps<T>, "as" | "className" | "children">;

/** A glass card. `interactive` adds the brand-gradient ring on hover. */
export function Panel<T extends ElementType = "div">({ as, interactive, padded = true, className, children, ...rest }: PanelProps<T>) {
  const Tag = (as ?? "div") as ElementType;
  return (
    <Tag
      className={cx(
        "glass rounded-2xl text-left shadow-sm",
        padded && "p-5 md:p-6",
        interactive && "ring-gradient cursor-pointer transition-transform duration-200 hover:-translate-y-0.5",
        className,
      )}
      {...rest}
    >
      {children}
    </Tag>
  );
}

export function SectionTitle({ icon, children, action }: { icon?: ReactNode; children: ReactNode; action?: ReactNode }) {
  return (
    <div className="mb-4 flex items-center justify-between gap-3">
      <h2 className="flex items-center gap-2 text-lg font-semibold text-foreground">
        {icon && <span className="text-accent">{icon}</span>}
        {children}
      </h2>
      {action}
    </div>
  );
}

const TONES = {
  neutral: "bg-default text-default-foreground",
  accent: "bg-accent-soft text-accent-soft-foreground",
  success: "bg-success-soft text-success-soft-foreground",
  warning: "bg-warning-soft text-warning-soft-foreground",
  danger: "bg-danger-soft text-danger-soft-foreground",
  warm: "bg-warm/15 text-warm",
  cool: "bg-cool/15 text-cool",
} as const;
export type Tone = keyof typeof TONES;

export function Chip({ children, tone = "neutral", className }: { children: ReactNode; tone?: Tone; className?: string }) {
  return (
    <span className={cx("inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium whitespace-nowrap", TONES[tone], className)}>
      {children}
    </span>
  );
}

/** Verdict colours from the frontend plan: proven/strong by the sign, likely yellow, suspicious orange, the rest grey. */
export function verdictTone(code: string | null | undefined, direction?: string | null): Tone {
  if (code === "proven" || code === "strong") return direction === "decreasing" ? "cool" : direction === "increasing" ? "warm" : "accent";
  if (code === "likely") return "warning";
  if (code === "suspicious") return "warm";
  return "neutral";
}

export function VerdictBadge({
  code,
  direction,
  size = "sm",
}: {
  code: string | null | undefined;
  direction?: string | null;
  size?: "sm" | "lg";
}) {
  const tr = useTr();
  const tone = verdictTone(code, direction);
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1.5 rounded-full font-semibold whitespace-nowrap",
        TONES[tone],
        size === "lg" ? "px-4 py-1.5 text-base" : "px-2.5 py-0.5 text-xs",
      )}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {verdictLabel(code, tr)}
    </span>
  );
}

export function Stat({ label, value, hint, tone }: { label: ReactNode; value: ReactNode; hint?: ReactNode; tone?: "warm" | "cool" | "accent" }) {
  const colour = tone === "warm" ? "text-warm" : tone === "cool" ? "text-cool" : tone === "accent" ? "text-accent" : "text-foreground";
  return (
    <div className="rounded-xl border border-[var(--glass-border)] bg-surface/40 p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-muted">{label}</p>
      <p className={cx("mt-1 text-2xl font-semibold tabular-nums", colour)}>{value}</p>
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </div>
  );
}

export function Progress({ value, className }: { value: number; className?: string }) {
  const width = Math.max(0, Math.min(100, value));
  return (
    <div className={cx("h-2 w-full overflow-hidden rounded-full bg-default", className)}>
      <div className="bg-gradient-brand h-full rounded-full transition-[width] duration-500" style={{ width: `${width}%` }} />
    </div>
  );
}

export function Field({ label, hint, children }: { label: ReactNode; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5 text-sm">
      <span className="font-medium text-foreground">{label}</span>
      {children}
      {hint && <span className="text-xs text-muted">{hint}</span>}
    </label>
  );
}

export function Input({ className, ...props }: ComponentProps<"input">) {
  return <input className={cx("field-control", className)} {...props} />;
}

export function Select({ className, ...props }: ComponentProps<"select">) {
  return <select className={cx("field-control", className)} {...props} />;
}

export function TextArea({ className, ...props }: ComponentProps<"textarea">) {
  return <textarea className={cx("field-control min-h-24 resize-y", className)} {...props} />;
}

export function Range({ label, value, ...props }: { label: ReactNode; value: number } & Omit<ComponentProps<"input">, "type" | "value">) {
  return (
    <label className="flex flex-col gap-2 text-sm">
      <span className="flex items-center justify-between">
        <span className="font-medium text-foreground">{label}</span>
        <span className="rounded-md bg-default px-2 py-0.5 text-xs font-semibold tabular-nums text-foreground">{value}</span>
      </span>
      <input type="range" className="range" value={value} {...props} />
    </label>
  );
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  className,
}: {
  options: Array<{ value: T; label: ReactNode }>;
  value: T;
  onChange: (value: T) => void;
  className?: string;
}) {
  return (
    <div role="tablist" className={cx("glass inline-flex max-w-full gap-1 overflow-x-auto rounded-xl p-1 scrollbar-none", className)}>
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(option.value)}
            className={cx(
              "whitespace-nowrap rounded-lg px-3 py-1.5 text-sm font-medium transition-colors",
              active ? "bg-gradient-brand text-white shadow" : "text-muted hover:text-foreground hover:bg-default",
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

export function Notice({ text, tone = "error" }: { text: string | null | undefined; tone?: "error" | "info" | "success" }) {
  if (!text) return null;
  const Icon = tone === "error" ? AlertTriangle : tone === "success" ? CheckCircle2 : Info;
  const colours =
    tone === "error"
      ? "border-danger/30 bg-danger-soft text-danger-soft-foreground"
      : tone === "success"
        ? "border-success/30 bg-success-soft text-success-soft-foreground"
        : "border-accent/30 bg-accent-soft text-accent-soft-foreground";
  return (
    <div role={tone === "error" ? "alert" : "status"} className={cx("mb-4 flex items-start gap-2 rounded-xl border px-4 py-3 text-sm", colours)}>
      <Icon size={16} className="mt-0.5 shrink-0" />
      <span>{text}</span>
    </div>
  );
}

export function EmptyState({ icon, title, text, action }: { icon?: ReactNode; title: ReactNode; text?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-2xl border border-dashed border-[var(--glass-border)] px-6 py-10 text-center">
      {icon && <div className="mb-1 text-muted">{icon}</div>}
      <p className="font-medium text-foreground">{title}</p>
      {text && <p className="max-w-sm text-sm text-muted">{text}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("animate-pulse rounded-xl bg-default", className)} />;
}

/** Signed number with an arrow, coloured by direction: warm for up, cool for down. */
export function Slope({ value, unit, digits = 3, className }: { value: number; unit?: ReactNode; digits?: number; className?: string }) {
  const up = value > 0;
  const flat = value === 0;
  return (
    <span className={cx("inline-flex items-baseline gap-1 font-semibold tabular-nums", flat ? "text-muted" : up ? "text-warm" : "text-cool", className)}>
      <span aria-hidden>{flat ? "→" : up ? "↑" : "↓"}</span>
      {up ? "+" : ""}
      {value.toFixed(digits)}
      {unit && <span className="text-xs font-normal text-muted">{unit}</span>}
    </span>
  );
}

/** Where the numbers of a case come from: a curated product, live NASA POWER, or a labelled demo series. */
export function DataSourceChip({ version }: { version: string | null | undefined }) {
  const tr = useTr();
  if (!version) return null;
  if (version.startsWith("nasa-power")) return <Chip tone="success"><Term id="nasa_power" bare>NASA POWER</Term></Chip>;
  if (version.startsWith("demo")) return <Chip tone="warning"><Term id="demo_data" bare>{tr("демо-дані", "demo data")}</Term></Chip>;
  return <Chip tone="accent">{tr("продукт аналітики", "analytics product")}</Chip>;
}

/**
 * A technical word with its plain-language explanation. Opens on hover, keyboard focus and tap.
 * `bare` drops the icon for tight places such as chips.
 */
export function Term({ id, children, bare = false }: { id: TermId; children?: ReactNode; bare?: boolean }) {
  const language = useStore((state) => state.language);
  const [open, setOpen] = useState(false);
  const tipId = useId();
  const [titleUk, textUk, titleEn, textEn] = TERMS[id];
  const title = language === "en" ? titleEn : titleUk;
  const text = language === "en" ? textEn : textUk;
  return (
    <span className="relative inline-flex items-center" onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
      <button
        type="button"
        className="inline-flex items-center gap-1 underline decoration-dotted decoration-1 underline-offset-4 outline-none focus-visible:rounded focus-visible:ring-2 focus-visible:ring-accent"
        aria-describedby={open ? tipId : undefined}
        onClick={(event) => {
          event.stopPropagation();
          setOpen((value) => !value);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={(event) => {
          if (event.key === "Escape") setOpen(false);
        }}
      >
        {children ?? title}
        {!bare && <CircleHelp size={13} className="shrink-0 opacity-60" aria-hidden />}
      </button>
      {open && (
        <span
          id={tipId}
          role="tooltip"
          className="absolute left-0 top-full z-50 mt-2 w-72 max-w-[80vw] rounded-xl border border-[var(--glass-border)] bg-surface p-3 text-left text-sm font-normal normal-case leading-snug tracking-normal text-foreground shadow-2xl"
        >
          <span className="mb-1 block font-semibold">{title}</span>
          <span className="block text-muted">{text}</span>
        </span>
      )}
    </span>
  );
}

/** The six verdict levels with what each means; the current one is highlighted. */
export function VerdictScale({ current }: { current?: string | null }) {
  const tr = useTr();
  const [open, setOpen] = useState(false);
  return (
    <div className="text-sm">
      <button type="button" className="flex items-center gap-1 text-accent hover:underline" onClick={() => setOpen((value) => !value)} aria-expanded={open}>
        {tr("Що означають вироки?", "What do verdicts mean?")}
        <ChevronDown size={14} className={cx("transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <ul className="mt-3 flex flex-col gap-2">
          {VERDICT_MEANING.map(([code, uk, en]) => (
            <li key={code} className={cx("flex items-start gap-3 rounded-lg p-2", code === current && "bg-accent-soft")}>
              <span className="w-36 shrink-0"><VerdictBadge code={code} /></span>
              <span className="text-muted">{tr(uk, en)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Evidence checks in words, each with a tick, a warning or a cross. */
export function CheckList({ checks }: { checks: Check[] }) {
  return (
    <ul className="flex flex-col gap-2">
      {checks.map((check) => {
        const Icon = check.status === "ok" ? CheckCircle2 : check.status === "warn" ? AlertTriangle : XCircle;
        const colour = check.status === "ok" ? "text-success" : check.status === "warn" ? "text-warning" : "text-danger";
        return (
          <li key={check.term} className="flex items-start gap-3 rounded-xl border border-[var(--glass-border)] px-4 py-3">
            <Icon size={18} className={cx("mt-0.5 shrink-0", colour)} aria-label={check.status} />
            <span className="text-foreground">{check.text}</span>
            <span className="ml-auto shrink-0 text-xs text-muted"><Term id={check.term}>{" "}</Term></span>
          </li>
        );
      })}
    </ul>
  );
}

/** Simple shows conclusions in words; Expert shows every number. */
export function ModeSwitch({ className }: { className?: string }) {
  const tr = useTr();
  const mode = useStore((state) => state.mode);
  const setMode = useStore((state) => state.setMode);
  return (
    <Segmented<"simple" | "expert">
      className={className}
      value={mode}
      onChange={setMode}
      options={[
        { value: "simple", label: tr("Просто", "Simple") },
        { value: "expert", label: tr("Експерт", "Expert") },
      ]}
    />
  );
}
