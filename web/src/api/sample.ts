/** A short monthly series the analyze and radar screens can send without a file upload. */
export function monthlySeries(variableId: string, regionId: string) {
  const dates: string[] = [];
  const values: number[] = [];
  for (let index = 0; index < 120; index += 1) {
    const year = 2005 + Math.floor(index / 12);
    const month = (index % 12) + 1;
    dates.push(`${year}-${String(month).padStart(2, "0")}-01`);
    values.push(Number((0.2 + index * 0.002).toFixed(4)));
  }
  return {
    meta: {
      variable_id: variableId,
      concept_id: variableId,
      dataset_id: "desktop",
      dataset_version: "1",
      units: "1",
      region_id: regionId,
      frequency: "monthly" as const,
    },
    dates,
    values,
  };
}
