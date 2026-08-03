import fs from "node:fs/promises";
import path from "node:path";


function displayValue(value) {
  if (typeof value === "string") return value.trim() || "—";
  if (!value || typeof value !== "object" || Array.isArray(value)) return "—";
  const status = String(value.status ?? "").trim();
  const summary = String(value.summary ?? value.note ?? "").trim();
  if (status && summary && status !== summary) return `${status}｜${summary}`;
  return status || summary || "—";
}

export async function loadEnrichment(root, asOf) {
  const source = path.join(root, "data", "processed", "enrichment", asOf, "technical_chip_summary.json");
  let payload;
  try {
    payload = JSON.parse(await fs.readFile(source, "utf8"));
  } catch {
    return {};
  }
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return {};
  if (!payload.stocks || typeof payload.stocks !== "object" || Array.isArray(payload.stocks)) return {};
  const fallbackDate = String(payload.as_of ?? asOf);
  return Object.fromEntries(Object.entries(payload.stocks).flatMap(([stockId, item]) => {
    if (!item || typeof item !== "object" || Array.isArray(item)) return [];
    return [[String(stockId), {
      technical: displayValue(item.technical),
      chip: displayValue(item.chip),
      sourceDate: String(item.source_date ?? fallbackDate),
    }]];
  }));
}
