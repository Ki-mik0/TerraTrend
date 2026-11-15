/**
 * Turn a case into plain sentences. Every number here comes from the case or its evidence;
 * nothing is invented. Thresholds follow the evidence protocol in docs/BEST_IMPLEMENTATION.md §4.
 */
import type { Translate } from "./i18n";
import type { TermId } from "./terms";

export type CheckStatus = "ok" | "warn" | "bad";

export interface Check {
  term: TermId;
  status: CheckStatus;
  text: string;
}

export interface EvidenceLike {
  witnesses_confirmed: number;
  witnesses_total: number;
  triangle_same_sign_share: number;
  alibi_b_raw: number;
  alibi_b_adjusted: number;
  quality: { gap_fraction: number; n_eff: number };
}

const SIGNIFICANT = new Set(["proven", "strong", "likely"]);

function fixed(value: number): string {
  const size = Math.abs(value);
  return size >= 10 ? size.toFixed(0) : size >= 1 ? size.toFixed(1) : size.toFixed(2);
}

/** One sentence: what changes, where, by how much, over which years. */
export function caseSentence(
  input: {
    variable: string;
    region: string;
    season: string;
    units: string;
    slope: number | null | undefined;
    direction: string | null | undefined;
    verdict: string | null | undefined;
    from: string;
    to: string;
  },
  tr: Translate,
): string {
  const where = `${input.variable} (${input.season.toLowerCase()}) — ${input.region}, ${input.from}–${input.to}`;
  if (input.verdict === "inadmissible") {
    return tr(`${where}: даних замало або вони неякісні, тож висновку немає.`, `${where}: too little or poor data, so there is no conclusion.`);
  }
  if (input.verdict === "no_evidence" || input.slope === null || input.slope === undefined || input.direction === "none") {
    return tr(`${where}: помітного тренду немає — зміни в межах звичайних коливань.`, `${where}: no noticeable trend — changes stay within normal ups and downs.`);
  }
  const up = (input.direction ?? (input.slope >= 0 ? "increasing" : "decreasing")) === "increasing";
  const amount = `${fixed(input.slope)}${input.units ? ` ${input.units}` : ""}`;
  return up
    ? tr(`${where}: зростає приблизно на ${amount} кожні 10 років.`, `${where}: rising by about ${amount} every 10 years.`)
    : tr(`${where}: спадає приблизно на ${amount} кожні 10 років.`, `${where}: falling by about ${amount} every 10 years.`);
}

/** The evidence protocol as checks a reader understands. */
export function evidenceChecks(evidence: EvidenceLike, verdict: string | null | undefined, tr: Translate): Check[] {
  const checks: Check[] = [];

  checks.push(
    SIGNIFICANT.has(verdict ?? "")
      ? { term: "significant", status: "ok", text: tr("Статистика: тренд надто виразний, щоб бути випадковістю.", "Statistics: the trend is too clear to be chance.") }
      : verdict === "suspicious"
        ? { term: "significant", status: "warn", text: tr("Статистика: щось є, але може бути й випадковістю.", "Statistics: something is there, but it may still be chance.") }
        : { term: "significant", status: "bad", text: tr("Статистика: тренд не відрізняється від випадкових коливань.", "Statistics: the trend is not distinguishable from chance.") },
  );

  const { witnesses_confirmed: confirmed, witnesses_total: total } = evidence;
  checks.push(
    total === 0
      ? { term: "witnesses", status: "warn", text: tr("Свідки: інших джерел для звірки немає.", "Witnesses: no other sources to cross-check.") }
      : confirmed / total >= 2 / 3
        ? { term: "witnesses", status: "ok", text: tr(`Свідки: ${confirmed} з ${total} незалежних джерел бачать те саме.`, `Witnesses: ${confirmed} of ${total} independent sources see the same.`) }
        : confirmed > 0
          ? { term: "witnesses", status: "warn", text: tr(`Свідки: лише ${confirmed} з ${total} джерел підтверджують.`, `Witnesses: only ${confirmed} of ${total} sources agree.`) }
          : { term: "witnesses", status: "bad", text: tr(`Свідки: жодне з ${total} джерел не підтверджує.`, `Witnesses: none of ${total} sources agree.`) },
  );

  const share = Math.round(evidence.triangle_same_sign_share * 100);
  checks.push({
    term: "robustness",
    status: share >= 80 ? "ok" : share >= 60 ? "warn" : "bad",
    text:
      share >= 80
        ? tr(`Стійкість: тренд тримається для ${share}% можливих періодів.`, `Robustness: the trend holds for ${share}% of possible periods.`)
        : tr(`Стійкість: лише ${share}% періодів дають той самий знак — висновок залежить від вибору років.`, `Robustness: only ${share}% of periods agree — the result depends on the chosen years.`),
  });

  const raw = Math.abs(evidence.alibi_b_raw);
  const kept = raw > 0 ? Math.abs(evidence.alibi_b_adjusted) / raw : 1;
  checks.push({
    term: "alibi",
    status: kept >= 0.7 ? "ok" : kept >= 0.4 ? "warn" : "bad",
    text:
      kept >= 0.7
        ? tr("Алібі: Ель-Ніньйо та інші природні причини не пояснюють тренд — він лишається.", "Alibi: El Niño and other natural causes do not explain the trend — it remains.")
        : kept >= 0.4
          ? tr("Алібі: природні причини пояснюють частину зміни, але тренд лишається.", "Alibi: natural causes explain part of the change, but the trend remains.")
          : tr("Алібі: більшу частину зміни пояснюють природні коливання.", "Alibi: natural variability explains most of the change."),
  });

  const gaps = Math.round(evidence.quality.gap_fraction * 100);
  checks.push({
    term: "quality",
    status: gaps <= 10 ? "ok" : gaps <= 20 ? "warn" : "bad",
    text: tr(`Якість: пропущено ${gaps}% місяців.`, `Quality: ${gaps}% of months are missing.`),
  });

  return checks;
}

/** A one-line comparison of two cases of the same variable. */
export function compareSentence(
  left: { region: string; slope: number | null | undefined },
  right: { region: string; slope: number | null | undefined },
  variable: string,
  units: string,
  tr: Translate,
): string | null {
  if (left.slope === null || left.slope === undefined || right.slope === null || right.slope === undefined) return null;
  const a = Math.abs(left.slope);
  const b = Math.abs(right.slope);
  if (Math.sign(left.slope) !== Math.sign(right.slope)) {
    return tr(
      `${variable}: у регіоні «${left.region}» і «${right.region}» тренди протилежні — один зростає, інший спадає.`,
      `${variable}: ${left.region} and ${right.region} move in opposite directions.`,
    );
  }
  const faster = a >= b ? left : right;
  const slower = a >= b ? right : left;
  const ratio = Math.min(a, b) > 0 ? Math.max(a, b) / Math.min(a, b) : null;
  const unit = units ? ` ${units}` : "";
  return tr(
    `${variable} змінюється швидше в регіоні «${faster.region}» (${fixed(faster.slope ?? 0)}${unit} за 10 років), ніж у «${slower.region}» (${fixed(slower.slope ?? 0)}${unit})${ratio && ratio >= 1.2 ? ` — приблизно в ${ratio.toFixed(1)} раза` : ""}.`,
    `${variable} changes faster in ${faster.region} (${fixed(faster.slope ?? 0)}${unit} per decade) than in ${slower.region} (${fixed(slower.slope ?? 0)}${unit})${ratio && ratio >= 1.2 ? ` — about ${ratio.toFixed(1)}×` : ""}.`,
  );
}
