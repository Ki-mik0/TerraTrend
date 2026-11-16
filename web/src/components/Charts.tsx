import { useMemo } from "react";
import ReactECharts from "echarts-for-react";
import { useTheme } from "../theme";

/** Chart colours follow the theme tokens in index.css; reading them again when the theme flips repaints the chart. */
function useChartColours() {
  const { resolvedTheme } = useTheme();
  return useMemo(() => {
    const style = getComputedStyle(document.documentElement);
    const read = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback;
    return {
      theme: resolvedTheme,
      axis: read("--chart-axis", "#94a3b8"),
      grid: read("--chart-grid", "#334155"),
      from: read("--chart-from", "#3b82f6"),
      to: read("--chart-to", "#10b981"),
      warm: read("--chart-warm", "#ef4444"),
      cool: read("--chart-cool", "#3b82f6"),
    };
  }, [resolvedTheme]);
}

function baseOption(colours: ReturnType<typeof useChartColours>, labels: string[]) {
  return {
    backgroundColor: "transparent",
    textStyle: { fontFamily: "Inter, system-ui, sans-serif" },
    tooltip: {
      trigger: "axis",
      backgroundColor: "rgba(15, 18, 28, 0.92)",
      borderWidth: 0,
      textStyle: { color: "#f1f5f9" },
    },
    grid: { left: 52, right: 16, top: 20, bottom: 32 },
    xAxis: {
      type: "category",
      data: labels,
      axisLabel: { color: colours.axis },
      axisLine: { lineStyle: { color: colours.grid } },
      axisTick: { show: false },
    },
    yAxis: {
      type: "value",
      axisLabel: { color: colours.axis },
      splitLine: { lineStyle: { color: colours.grid, type: "dashed" } },
    },
  };
}

export function LineChart({ values, name, height = 300 }: { values: number[]; name: string; height?: number }) {
  const colours = useChartColours();
  const option = {
    ...baseOption(colours, values.map((_, index) => String(index + 1))),
    series: [
      {
        type: "line",
        name,
        data: values,
        smooth: true,
        showSymbol: false,
        lineStyle: {
          width: 2.5,
          color: { type: "linear", x: 0, y: 0, x2: 1, y2: 0, colorStops: [{ offset: 0, color: colours.from }, { offset: 1, color: colours.to }] },
        },
        areaStyle: {
          color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: `${colours.from}55` }, { offset: 1, color: `${colours.from}00` }] },
        },
      },
    ],
  };
  return <ReactECharts key={colours.theme} style={{ height }} option={option} notMerge />;
}

/** Bars coloured by sign: warm for an upward slope, cool for a downward one, with a zero line. */
export function BarChart({ labels, values, height = 300 }: { labels: string[]; values: number[]; height?: number }) {
  const colours = useChartColours();
  const option = {
    ...baseOption(colours, labels),
    series: [
      {
        type: "bar",
        data: values.map((value) => ({ value, itemStyle: { color: value >= 0 ? colours.warm : colours.cool, borderRadius: value >= 0 ? [6, 6, 0, 0] : [0, 0, 6, 6] } })),
        barMaxWidth: 28,
        markLine: { silent: true, symbol: "none", lineStyle: { color: colours.axis, type: "solid", width: 1 }, label: { show: false }, data: [{ yAxis: 0 }] },
      },
    ],
  };
  return <ReactECharts key={colours.theme} style={{ height }} option={option} notMerge />;
}
