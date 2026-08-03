#!/usr/bin/env node
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";


const inputPath = process.argv[2] ?? "reports/momentum/latest/screening_results.json";
const outputPath = process.argv[3] ?? "outputs/latest/台股營運動能.xlsx";
const root = process.cwd();
const payload = JSON.parse(await fs.readFile(inputPath, "utf8"));
const { metadata: meta, config, checks, results } = payload;
const MILLION = 1_000_000;

function scaled(value, divisor) {
  return value == null ? null : Number(value) / divisor;
}

async function moveInspectSidecar(xlsxPath, qaDirectory) {
  const sidecarPath = `${xlsxPath}.inspect.ndjson`;
  const destination = path.join(qaDirectory, `${path.basename(xlsxPath)}.inspect.ndjson`);
  try {
    await fs.rename(sidecarPath, destination);
  } catch (error) {
    if (error?.code === "ENOENT") return;
    if (error?.code !== "EXDEV") throw error;
    await fs.copyFile(sidecarPath, destination);
    await fs.unlink(sidecarPath);
  }
}

const workbook = Workbook.create();
const dashboard = workbook.worksheets.add("儀表板");
const explanation = workbook.worksheets.add("模型說明");
const ranking = workbook.worksheets.add("動能排名");
const rejected = workbook.worksheets.add("未通過明細");
const audit = workbook.worksheets.add("試算稽核");
const review = workbook.worksheets.add("人工複核");
const assumptions = workbook.worksheets.add("參數");
const checkSheet = workbook.worksheets.add("檢核");
const sources = workbook.worksheets.add("資料來源");

const colors = {
  forest: "#173F35",
  green: "#147D64",
  amber: "#B45309",
  lightGreen: "#E7F5EF",
  lightAmber: "#FEF3C7",
  lightBlue: "#EAF1F8",
  lightGray: "#EEF2F6",
  white: "#FFFFFF",
  black: "#111827",
  blue: "#0000FF",
  red: "#DC2626",
  gray: "#64748B",
};

for (const sheet of [dashboard, explanation, ranking, rejected, audit, review, assumptions, checkSheet, sources]) {
  sheet.showGridLines = false;
}

function titleBand(sheet, range, text) {
  sheet.getRange(range).merge();
  const cell = sheet.getRange(range.split(":")[0]);
  cell.values = [[text]];
  cell.format = {
    fill: colors.forest,
    font: { bold: true, color: colors.white, size: 18 },
    verticalAlignment: "center",
  };
  sheet.getRange(range).format.rowHeight = 34;
}

function formatHeader(range) {
  range.format = {
    fill: colors.forest,
    font: { bold: true, color: colors.white, size: 9 },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "outside", style: "thin", color: "#94A3B8" },
  };
}

function setColumnWidth(sheet, column, lastRow, width) {
  sheet.getRange(`${column}1:${column}${lastRow}`).format.columnWidth = width;
}

function linearFormula(cell, row) {
  return `IF(OR(${cell}="",NOT(ISNUMBER(${cell}))),0,'參數'!$E$${row}*MAX(0,MIN(1,(${cell}-'參數'!$C$${row})/('參數'!$D$${row}-'參數'!$C$${row}))))`;
}

function descendingFormula(cell, row) {
  return `IF(OR(${cell}="",NOT(ISNUMBER(${cell}))),0,'參數'!$E$${row}*MAX(0,MIN(1,('參數'!$D$${row}-${cell})/('參數'!$D$${row}-'參數'!$C$${row}))))`;
}

// 模型說明
titleBand(explanation, "A1:H1", "高品質營運動能模型說明");
explanation.getRange("A3:H3").merge();
explanation.getRange("A3").values = [["核心概念"]];
explanation.getRange("A3:H3").format = { fill: colors.green, font: { bold: true, color: colors.white, size: 12 } };
explanation.getRange("A4:H8").merge();
explanation.getRange("A4").values = [["這套模型以「高品質營運動能」為核心，尋找營收、獲利與營益率正在改善，而且成長能獲得現金流與財務體質支持的公司。\n\n模型關注的是企業營運是否加速，而不是短期股價上漲。營收成長若未反映至獲利、營益率或現金流，會降低評價；單月暴增、低基期轉盈及一次性收益也會另外標示。量化排名只用來縮小研究範圍，不代表預期報酬或買進建議。Excel 顯示單位：成交額為百萬元。"]];
explanation.getRange("A4:H8").format = { fill: colors.lightBlue, font: { color: colors.black, size: 11 }, wrapText: true, verticalAlignment: "center" };
explanation.getRange("A10:H10").merge();
explanation.getRange("A10").values = [["篩選流程"]];
explanation.getRange("A10:H10").format = { fill: colors.green, font: { bold: true, color: colors.white, size: 12 } };
const momentumSteps = [
  ["1 建立母體", "納入上市、上櫃四位數普通股，排除ETF、存託憑證；金融業採獨立方式處理。"],
  ["2 資料與流動性", "確認最近六個月營收、至少三年財報資料，且20日平均成交金額至少5,000萬元。"],
  ["3 品質門檻", "要求TTM淨利為正，排除重大負債異常、資料缺漏及人工否決公司；前期虧損者另列轉機觀察。"],
  ["4 動能60分", "評估近三月與最新月營收年增、營收加速度、TTM淨利成長、同業營益率位置及營益率改善。"],
  ["5 品質25分", "檢視獲利連續性、自由現金流、最近完整年度現金轉換能力、負債安全與淨現金。"],
  ["6 估值流動性15分", "比較同業PER、PBR位置、絕對本益比及20日平均成交金額。"],
  ["7 研究漏斗", "通過門檻後依總分排序，前100名列入觀察名單，前20名列為優先研究對象。"],
  ["8 質化覆核", "確認成長來源、競爭優勢、治理風險、低基期效應與一次性因素，判斷動能延續性。"],
];
momentumSteps.forEach(([label, description], index) => {
  const row = 12 + index * 2;
  explanation.getRange(`A${row}:B${row + 1}`).merge();
  explanation.getRange(`C${row}:H${row + 1}`).merge();
  explanation.getRange(`A${row}`).values = [[label]];
  explanation.getRange(`C${row}`).values = [[description]];
  explanation.getRange(`A${row}:B${row + 1}`).format = { fill: index % 2 ? colors.lightGray : colors.lightGreen, font: { bold: true, color: colors.forest }, verticalAlignment: "center" };
  explanation.getRange(`C${row}:H${row + 1}`).format = { fill: index % 2 ? "#F8FAFC" : "#F0FDF4", wrapText: true, verticalAlignment: "center" };
  explanation.getRange(`A${row}:H${row + 1}`).format.borders = { preset: "outside", style: "thin", color: "#CBD5E1" };
});
for (const col of ["A", "B"]) setColumnWidth(explanation, col, 28, 13);
for (const col of ["C", "D", "E", "F", "G", "H"]) setColumnWidth(explanation, col, 28, 16);
explanation.getRange("A4:H8").format.rowHeight = 25;

// 參數
titleBand(assumptions, "A1:E1", "營運動能模型參數");
assumptions.getRange("A2:E2").merge();
assumptions.getRange("A2").values = [["藍字為可調整參數；分數公式會即時重算，但修改門檻後須重新執行掃描才會重新排序。"]];
assumptions.getRange("A2").format = { font: { color: colors.gray, italic: true }, wrapText: true };
assumptions.getRange("A4:E4").values = [["類別", "參數／指標", "下限／最佳", "目標／最差", "分數"]];
formatHeader(assumptions.getRange("A4:E4"));
assumptions.getRange("A5:E7").values = [
  ["權重", "營運動能", config.weights.operating_momentum, null, null],
  ["權重", "動能品質", config.weights.quality, null, null],
  ["權重", "估值與流動性", config.weights.valuation_liquidity, null, null],
];
assumptions.getRange("A9:E9").merge();
assumptions.getRange("A9").values = [["硬性門檻"]];
assumptions.getRange("A9:E9").format = { fill: colors.green, font: { bold: true, color: colors.white } };
assumptions.getRange("A10:E15").values = [
  ["硬門檻", "完整獲利資料", config.hard_gates.min_complete_profit_years, "年", null],
  ["硬門檻", "最高負債／資產", config.hard_gates.max_liabilities_to_assets, "比例", null],
  ["硬門檻", "最低20日均成交額", config.hard_gates.min_avg_daily_turnover_twd, "TWD", null],
  ["硬門檻", "TTM淨利為正", config.hard_gates.require_positive_ttm_income ? 1 : 0, "0/1", null],
  ["硬門檻", "前期TTM淨利為正", config.hard_gates.require_positive_prior_ttm_income ? 1 : 0, "0/1", null],
  ["硬門檻", "營收加速度資料完整", config.hard_gates.require_revenue_acceleration_data ? 1 : 0, "0/1", null],
];
assumptions.getRange("A17:E17").merge();
assumptions.getRange("A17").values = [["評分端點與細項分數"]];
assumptions.getRange("A17:E17").format = { fill: colors.green, font: { bold: true, color: colors.white } };
const t = config.score_targets;
const p = config.components;
assumptions.getRange("A18:E34").values = [
  ["營運動能", "近3月營收YoY", t.revenue_growth_floor, t.revenue_growth_target, p.operating_momentum.revenue_3m_yoy],
  ["營運動能", "最新月營收YoY", t.revenue_growth_floor, t.revenue_growth_target, p.operating_momentum.latest_revenue_yoy],
  ["營運動能", "營收加速度", t.revenue_acceleration_floor, t.revenue_acceleration_target, p.operating_momentum.revenue_acceleration],
  ["營運動能", "TTM淨利成長", t.net_income_growth_floor, t.net_income_growth_target, p.operating_momentum.ttm_net_income_growth],
  ["營運動能", "同業營益率分位", 0, 1, p.operating_momentum.sector_margin_percentile],
  ["營運動能", "營益率年變化", t.margin_change_floor, t.margin_change_target, p.operating_momentum.operating_margin_change],
  ["動能品質", "獲利年數", 0, 5, p.quality.profitable_years],
  ["動能品質", "正FCF年數", 0, 5, p.quality.positive_fcf_years],
  ["動能品質", "現金轉換", t.cash_conversion_floor, t.cash_conversion_target, p.quality.cash_conversion],
  ["動能品質", "負債／資產", t.liabilities_ratio_best, t.liabilities_ratio_worst, p.quality.liabilities_ratio],
  ["動能品質", "淨現金／市值", t.net_cash_ratio_floor, t.net_cash_ratio_target, p.quality.net_cash_ratio],
  ["估值流動性", "同業PER分位", 0, 1, p.valuation_liquidity.sector_per_percentile],
  ["估值流動性", "同業PBR分位", 0, 1, p.valuation_liquidity.sector_pbr_percentile],
  ["估值流動性", "絕對PER", t.per_best, t.per_worst, p.valuation_liquidity.absolute_per],
  ["估值流動性", "20日均成交額", config.hard_gates.min_avg_daily_turnover_twd, t.turnover_target_twd, p.valuation_liquidity.turnover],
  ["說明", "營收資料期", null, null, null],
  ["說明", meta.latest_revenue_period, null, null, null],
];
assumptions.getRange("C5:E34").format.font = { color: colors.blue };
assumptions.getRange("C10:C15").format.fill = colors.lightAmber;
assumptions.getRange("C18:E34").format.fill = colors.lightAmber;
assumptions.getRange("C11").format.numberFormat = "0.0%";
for (const row of [18, 19, 20, 21, 22, 23, 27, 28, 29, 30]) assumptions.getRange(`C${row}:D${row}`).format.numberFormat = "0.0%";
assumptions.getRange("C24:D25").format.numberFormat = "0";
assumptions.getRange("C26:D26").format.numberFormat = "0.00x";
assumptions.getRange("C31:D31").format.numberFormat = "0.0";
assumptions.getRange("C32:D32").format.numberFormat = "#,##0";
setColumnWidth(assumptions, "A", 34, 16);
setColumnWidth(assumptions, "B", 34, 28);
for (const col of ["C", "D", "E"]) setColumnWidth(assumptions, col, 34, 16);

// 精簡主排名：只呈現通過硬門檻的公司，分數為本次模型輸出的靜態值。
const passingRows = results.filter((row) => row.hard_pass);
const rejectedRows = results.filter((row) => !row.hard_pass);
titleBand(ranking, "A1:Y1", "台股營運動能排名｜硬門檻通過");
ranking.getRange("A2:Y2").merge();
ranking.getRange("A2").values = [[`市場資料 ${meta.latest_market_date}｜營收期 ${meta.latest_revenue_period}｜財報季 ${meta.latest_financial_quarter}｜共 ${passingRows.length} 檔；完整欄位請查 screening_results.csv。`]];
ranking.getRange("A2").format = { fill: colors.lightBlue, font: { color: colors.gray }, wrapText: true };
ranking.getRange("A3:Y3").merge();
ranking.getRange("A3").values = [["本頁為靜態模型結果，不因工作簿參數變動而改寫；公式重算與抽樣驗證請見「試算稽核」。"]];
ranking.getRange("A3").format = { font: { italic: true, color: colors.gray } };
const mainHeaders = [
  "排名", "代碼", "公司", "產業", "漏斗階段", "分類", "治理狀態", "收盤價", "20日均成交額(百萬元)", "PER", "PBR",
  "近3月營收YoY", "單月營收YoY", "營收加速度", "TTM淨利成長", "營益率年變化", "獲利年數", "正FCF年數",
  "現金轉換", "負債/資產", "淨現金/市值", "營運動能分", "動能品質分", "估值流動性分", "總分",
];
ranking.getRange("A5:Y5").values = [mainHeaders];
formatHeader(ranking.getRange("A5:Y5"));
ranking.getRange("A5:Y5").format.rowHeight = 44;
const mainRows = passingRows.map((row) => [
  row.rank, row.stock_id, row.stock_name, row.industry, row.funnel_stage, row.momentum_bucket, row.governance_status,
  row.close, scaled(row.avg_daily_turnover, MILLION), row.per, row.pbr, row.revenue_3m_yoy, row.latest_revenue_yoy,
  row.revenue_acceleration, row.ttm_net_income_growth, row.ttm_operating_margin_change, row.profitable_years,
  row.positive_fcf_years, row.cash_conversion, row.liabilities_ratio, row.net_cash_ratio, row.operating_momentum_score,
  row.quality_score, row.valuation_liquidity_score, row.total_score,
]);
const rankingLastRow = 5 + mainRows.length;
if (mainRows.length) {
  ranking.getRange(`A6:Y${rankingLastRow}`).values = mainRows;
  ranking.getRange(`H6:H${rankingLastRow}`).format.numberFormat = "#,##0.00";
  ranking.getRange(`I6:I${rankingLastRow}`).format.numberFormat = '#,##0"百萬"';
  ranking.getRange(`J6:K${rankingLastRow}`).format.numberFormat = "0.0x";
  ranking.getRange(`L6:P${rankingLastRow}`).format.numberFormat = "0.0%";
  ranking.getRange(`S6:S${rankingLastRow}`).format.numberFormat = "0.00x";
  ranking.getRange(`T6:U${rankingLastRow}`).format.numberFormat = "0.0%";
  ranking.getRange(`V6:Y${rankingLastRow}`).format.numberFormat = "0.0";
  ranking.getRange(`Y6:Y${rankingLastRow}`).conditionalFormats.add("colorScale", {
    criteria: [
      { type: "lowestValue", color: "#FEE2E2" },
      { type: "percentile", value: 50, color: "#FEF3C7" },
      { type: "highestValue", color: "#DCFCE7" },
    ],
  });
  const table = ranking.tables.add(`A5:Y${rankingLastRow}`, true, "MomentumPassingRankingTable");
  table.style = "TableStyleMedium4";
}
ranking.freezePanes.freezeRows(5);
ranking.freezePanes.freezeColumns(4);
const mainWidths = { A: 8, B: 9, C: 15, D: 18, E: 12, F: 13, G: 12, H: 11, I: 18, J: 10, K: 10, L: 14, M: 14, N: 14, O: 15, P: 14, Q: 10, R: 11, S: 12, T: 12, U: 13, V: 13, W: 13, X: 15, Y: 10 };
for (const [col, width] of Object.entries(mainWidths)) setColumnWidth(ranking, col, Math.max(6, rankingLastRow), width);

titleBand(rejected, "A1:F1", "未通過動能硬門檻明細");
rejected.getRange("A2:F2").merge();
rejected.getRange("A2").values = [[`共 ${rejectedRows.length} 檔；完整 33 欄結果保留於 reports/momentum/${meta.as_of}/screening_results.csv。`]];
rejected.getRange("A2").format = { fill: colors.lightBlue, font: { color: colors.gray }, wrapText: true };
rejected.getRange("A5:F5").values = [["代碼", "公司", "產業", "未通過原因", "缺漏旗標", "總分"]];
formatHeader(rejected.getRange("A5:F5"));
const rejectedValues = rejectedRows.map((row) => [row.stock_id, row.stock_name, row.industry, row.exclusion_reasons, row.missing_flags, row.total_score]);
const rejectedLastRow = 5 + rejectedValues.length;
if (rejectedValues.length) {
  rejected.getRange(`A6:F${rejectedLastRow}`).values = rejectedValues;
  rejected.getRange(`D6:E${rejectedLastRow}`).format.wrapText = true;
  rejected.getRange(`F6:F${rejectedLastRow}`).format.numberFormat = "0.0";
  const table = rejected.tables.add(`A5:F${rejectedLastRow}`, true, "MomentumRejectedDetailTable");
  table.style = "TableStyleMedium4";
}
rejected.freezePanes.freezeRows(5);
for (const [col, width] of Object.entries({ A: 9, B: 15, C: 18, D: 52, E: 24, F: 10 })) setColumnWidth(rejected, col, Math.max(6, rejectedLastRow), width);

const selectedAuditRows = new Map();
function includeAuditRow(row) {
  if (row) selectedAuditRows.set(row.stock_id, row);
}
for (const rank of [1, 10, 20, 100, 200]) includeAuditRow(passingRows.find((row) => row.rank === rank));
includeAuditRow(passingRows.at(-1));
includeAuditRow(rejectedRows[0]);
includeAuditRow(rejectedRows.find((row) => row.missing_flags));
includeAuditRow(rejectedRows.find((row) => row.momentum_bucket === "轉機觀察"));
includeAuditRow(rejectedRows.find((row) => row.momentum_bucket === "前期資料不足"));
const auditRows = [...selectedAuditRows.values()];
titleBand(audit, "A1:AG1", "代表性公式試算稽核");
audit.getRange("A2:AG2").merge();
audit.getRange("A2").values = [[`抽查 ${auditRows.length} 檔：排名前段／邊界／最後通過者／缺值、轉機與前期資料不足案例；綠字公式須與 Python pipeline 一致。`]];
audit.getRange("A2").format = { fill: colors.lightBlue, font: { color: colors.gray }, wrapText: true };
const auditHeaders = [
  "排名", "代碼", "公司", "產業", "市場", "漏斗階段", "治理狀態", "未通過原因", "收盤價", "20日均成交額(百萬元)", "PER", "PBR",
  "近3月營收YoY", "單月營收YoY", "營收加速度", "TTM淨利成長", "TTM營益率", "營益率年變化", "獲利年數", "正FCF年數",
  "現金轉換", "負債/資產", "淨現金/市值", "同業PER分位", "同業PBR分位", "同業營益率分位", "營運動能分", "動能品質分",
  "估值流動性分", "總分", "硬門檻", "缺漏旗標", "模型短評（自動）",
];
audit.getRange("A5:AG5").values = [auditHeaders];
formatHeader(audit.getRange("A5:AG5"));
audit.getRange("A5:AG5").format.rowHeight = 44;
const auditValues = auditRows.map((row) => [
  row.rank, row.stock_id, row.stock_name, row.industry, row.market, row.funnel_stage, row.governance_status,
  row.exclusion_reasons, row.close, scaled(row.avg_daily_turnover, MILLION), row.per, row.pbr, row.revenue_3m_yoy, row.latest_revenue_yoy,
  row.revenue_acceleration, row.ttm_net_income_growth, row.ttm_operating_margin, row.ttm_operating_margin_change,
  row.profitable_years, row.positive_fcf_years, row.cash_conversion, row.liabilities_ratio, row.net_cash_ratio,
  row.sector_per_percentile, row.sector_pbr_percentile, row.sector_margin_percentile, null, null, null, null,
  row.hard_pass, row.missing_flags, row.model_summary,
]);
const auditFirstDataRow = 6;
const auditLastRow = 5 + auditValues.length;
if (auditValues.length) {
  audit.getRange(`A${auditFirstDataRow}:AG${auditLastRow}`).values = auditValues;
  const formulaRows = auditRows.map((_, index) => auditFirstDataRow + index);
  audit.getRange(`AA${auditFirstDataRow}:AA${auditLastRow}`).formulas = formulaRows.map((r) => [
    `=${linearFormula(`M${r}`, 18)}+${linearFormula(`N${r}`, 19)}+${linearFormula(`O${r}`, 20)}+${linearFormula(`P${r}`, 21)}+${linearFormula(`Z${r}`, 22)}+${linearFormula(`R${r}`, 23)}`,
  ]);
  audit.getRange(`AB${auditFirstDataRow}:AB${auditLastRow}`).formulas = formulaRows.map((r) => [
    `=${linearFormula(`S${r}`, 24)}+${linearFormula(`T${r}`, 25)}+${linearFormula(`U${r}`, 26)}+${descendingFormula(`V${r}`, 27)}+${linearFormula(`W${r}`, 28)}`,
  ]);
  audit.getRange(`AC${auditFirstDataRow}:AC${auditLastRow}`).formulas = formulaRows.map((r) => [
    `=${descendingFormula(`X${r}`, 29)}+${descendingFormula(`Y${r}`, 30)}+${descendingFormula(`K${r}`, 31)}+${linearFormula(`J${r}*1000000`, 32)}`,
  ]);
  audit.getRange(`AD${auditFirstDataRow}:AD${auditLastRow}`).formulas = formulaRows.map((r) => [`=AA${r}+AB${r}+AC${r}`]);
  audit.getRange(`I${auditFirstDataRow}:L${auditLastRow}`).format.numberFormat = "#,##0.0";
  audit.getRange(`J${auditFirstDataRow}:J${auditLastRow}`).format.numberFormat = '#,##0"百萬"';
  audit.getRange(`M${auditFirstDataRow}:R${auditLastRow}`).format.numberFormat = "0.0%";
  audit.getRange(`U${auditFirstDataRow}:U${auditLastRow}`).format.numberFormat = "0.00x";
  audit.getRange(`V${auditFirstDataRow}:Z${auditLastRow}`).format.numberFormat = "0.0%";
  audit.getRange(`AA${auditFirstDataRow}:AD${auditLastRow}`).format.numberFormat = "0.0";
  audit.getRange(`AA${auditFirstDataRow}:AD${auditLastRow}`).format.font = { color: colors.green };
  audit.getRange(`AG${auditFirstDataRow}:AG${auditLastRow}`).format = { wrapText: true, verticalAlignment: "center" };
  const table = audit.tables.add(`A5:AG${auditLastRow}`, true, "MomentumFormulaAuditTable");
  table.style = "TableStyleMedium4";
}
audit.freezePanes.freezeRows(5);
audit.freezePanes.freezeColumns(4);
const auditWidths = {
  A: 8, B: 9, C: 15, D: 18, E: 9, F: 13, G: 12, H: 40, I: 11, J: 18, K: 10, L: 10,
  M: 14, N: 14, O: 14, P: 15, Q: 13, R: 14, S: 10, T: 11, U: 12, V: 12, W: 13, X: 12, Y: 12,
  Z: 14, AA: 13, AB: 13, AC: 15, AD: 10, AE: 10, AF: 20, AG: 54,
};
for (const [col, width] of Object.entries(auditWidths)) setColumnWidth(audit, col, Math.max(6, auditLastRow), width);

// 儀表板
titleBand(dashboard, "A1:Q1", "台股高品質營運動能篩選儀表板");
dashboard.getRange("A2:Q2").merge();
dashboard.getRange("A2").values = [[`市場資料 ${meta.latest_market_date}｜營收期 ${meta.latest_revenue_period}｜財報季 ${meta.latest_financial_quarter}｜僅供研究篩選，非投資建議`]];
dashboard.getRange("A2").format = { fill: colors.lightBlue, font: { color: colors.gray }, wrapText: true };
const cardLabels = ["普通股母體", "動能門檻通過", "觀察前100", "精華20", "轉機觀察", "前期資料不足", "模型狀態"];
const cardValues = [meta.universe_count, meta.hard_pass_count, meta.watchlist_count, meta.focus_count, meta.turnaround_count, meta.insufficient_history_count, meta.model_status];
for (let index = 0; index < 7; index += 1) {
  const startCol = String.fromCharCode("A".charCodeAt(0) + index * 2);
  const endCol = String.fromCharCode(startCol.charCodeAt(0) + 1);
  dashboard.getRange(`${startCol}4:${endCol}4`).merge();
  dashboard.getRange(`${startCol}5:${endCol}5`).merge();
  dashboard.getRange(`${startCol}4`).values = [[cardLabels[index]]];
  dashboard.getRange(`${startCol}5`).values = [[cardValues[index]]];
  dashboard.getRange(`${startCol}4:${endCol}4`).format = { fill: colors.lightGray, font: { bold: true, color: colors.gray }, horizontalAlignment: "center" };
  dashboard.getRange(`${startCol}5:${endCol}5`).format = { font: { bold: true, color: index === 6 ? colors.green : colors.amber, size: 16 }, horizontalAlignment: "center" };
}
dashboard.getRange("A7:H7").merge();
dashboard.getRange("A7").values = [["營運動能精華候選（仍需成長來源與治理質化覆核）"]];
dashboard.getRange("A7:H7").format = { fill: colors.green, font: { bold: true, color: colors.white } };
dashboard.getRange("A8:H8").values = [["排名", "代碼", "公司", "產業", "動能", "品質", "估值流動性", "總分"]];
formatHeader(dashboard.getRange("A8:H8"));
const focusRows = passingRows.slice(0, config.report.focus_size);
if (focusRows.length) {
  dashboard.getRange(`A9:H${8 + focusRows.length}`).values = focusRows.map((row) => [
    row.rank, row.stock_id, row.stock_name, row.industry, row.operating_momentum_score, row.quality_score,
    row.valuation_liquidity_score, row.total_score,
  ]);
  dashboard.getRange(`E9:H${8 + focusRows.length}`).format.numberFormat = "0.0";
  dashboard.getRange(`A8:H${8 + focusRows.length}`).format.borders = { preset: "outside", style: "thin", color: "#CBD5E1" };
}
dashboard.getRange("J27:K27").values = [["公司", "總分"]];
formatHeader(dashboard.getRange("J27:K27"));
const chartRows = focusRows.slice(0, 10);
if (chartRows.length) {
  dashboard.getRange(`J28:J${27 + chartRows.length}`).values = chartRows.map((row) => [`${row.stock_id} ${row.stock_name}`]);
  dashboard.getRange(`K28:K${27 + chartRows.length}`).formulas = chartRows.map((_, index) => [`=H${9 + index}`]);
  dashboard.getRange(`K28:K${27 + chartRows.length}`).format.numberFormat = "0.0";
  const chart = dashboard.charts.add("bar", dashboard.getRange(`J27:K${27 + chartRows.length}`));
  chart.title = "Top 10 營運動能綜合分數";
  chart.hasLegend = false;
  chart.yAxis = { numberFormatCode: "0.0", min: 0, max: 100 };
  chart.setPosition("J7", "Q24");
}
dashboard.getRange("L27:Q34").merge();
dashboard.getRange("L27").values = [["營運動能排名不是買進建議。單月暴增、低基期、轉盈與一次性收益須人工覆核；月營收或季報更新時，營運排名變化才具有主要研究意義。"]];
dashboard.getRange("L27:Q34").format = { fill: colors.lightAmber, font: { color: "#92400E" }, wrapText: true, verticalAlignment: "center" };
dashboard.freezePanes.freezeRows(2);
for (const col of ["A", "B", "E", "F", "G", "H"]) setColumnWidth(dashboard, col, 34, 12);
setColumnWidth(dashboard, "C", 34, 15);
setColumnWidth(dashboard, "D", 34, 17);
setColumnWidth(dashboard, "I", 34, 3);
for (const col of ["J", "K", "L", "M", "N", "O", "P", "Q"]) setColumnWidth(dashboard, col, 34, 13);

// 人工複核
titleBand(review, "A1:L1", "營運動能精華20人工質化複核");
review.getRange("A2:L2").merge();
review.getRange("A2").values = [["模型短評由營運與財務欄位自動產生；黃色藍字欄位可編輯，永久保存請同步更新 config/manual_review.csv。"]];
review.getRange("A2").format = { fill: colors.lightAmber, font: { color: "#92400E" }, wrapText: true };
review.getRange("A5:L5").values = [["排名", "代碼", "公司", "產業", "總分", "治理狀態", "成長來源／催化", "人工排除", "複核筆記", "模型短評（自動）", "量化狀態", "質化結論"]];
formatHeader(review.getRange("A5:L5"));
if (focusRows.length) {
  const reviewValues = focusRows.map((row) => [
    row.rank, row.stock_id, row.stock_name, row.industry, row.total_score, row.governance_status, row.catalyst,
    row.manual_exclude ? "是" : "否", row.manual_notes, row.model_summary, "動能硬門檻通過", null,
  ]);
  const reviewLastRow = 5 + reviewValues.length;
  review.getRange(`A6:L${reviewLastRow}`).values = reviewValues;
  review.getRange(`L6:L${reviewLastRow}`).formulas = focusRows.map((_, index) => {
    const r = 6 + index;
    return [`=IF(F${r}="否決","排除",IF(AND(F${r}="通過",G${r}<>""),"可進深度研究","待完成質化"))`];
  });
  review.getRange(`E6:E${reviewLastRow}`).format.numberFormat = "0.0";
  review.getRange(`F6:I${reviewLastRow}`).format = { fill: colors.lightAmber, font: { color: colors.blue }, wrapText: true };
  review.getRange(`J6:J${reviewLastRow}`).format = { fill: colors.lightBlue, wrapText: true, verticalAlignment: "center" };
  review.getRange(`J6:J${reviewLastRow}`).format.rowHeight = 38;
  review.getRange(`L6:L${reviewLastRow}`).format.font = { bold: true, color: colors.black };
  review.getRange(`F6:F${reviewLastRow}`).dataValidation = { rule: { type: "list", values: ["待複核", "通過", "否決"] } };
  review.getRange(`H6:H${reviewLastRow}`).dataValidation = { rule: { type: "list", values: ["否", "是"] } };
  review.getRange(`A5:L${reviewLastRow}`).format.borders = { preset: "outside", style: "thin", color: "#CBD5E1" };
}
review.freezePanes.freezeRows(5);
const reviewWidths = { A: 8, B: 9, C: 14, D: 16, E: 10, F: 13, G: 26, H: 12, I: 30, J: 52, K: 18, L: 18 };
for (const [col, width] of Object.entries(reviewWidths)) setColumnWidth(review, col, 30, width);

// 檢核
titleBand(checkSheet, "A1:G1", "營運動能模型檢核");
checkSheet.getRange("A2").values = [["整體狀態"]];
checkSheet.getRange("B2").values = [[meta.model_status]];
checkSheet.getRange("A2:B2").format = { fill: colors.lightBlue, font: { bold: true }, borders: { preset: "outside", style: "thin", color: "#CBD5E1" } };
checkSheet.getRange("B2").format.font = { bold: true, color: meta.model_status === "OK" ? colors.green : colors.red };
checkSheet.getRange("A5:G5").values = [["檢核", "實際", "預期", "差異", "容忍值", "狀態", "說明"]];
formatHeader(checkSheet.getRange("A5:G5"));
checkSheet.getRange(`A6:G${5 + checks.length}`).values = checks.map((item) => [item.check, item.actual, item.expected, null, item.tolerance, item.status, item.notes]);
checkSheet.getRange(`D6:D${5 + checks.length}`).formulas = checks.map((item, index) => {
  const r = 6 + index;
  return [typeof item.actual === "number" && typeof item.expected === "number" ? `=B${r}-C${r}` : ""];
});
checkSheet.getRange(`A5:G${5 + checks.length}`).format.borders = { preset: "outside", style: "thin", color: "#CBD5E1" };
checkSheet.getRange("B7:D9").format.numberFormat = "0.0%";
setColumnWidth(checkSheet, "A", 20, 28);
for (const col of ["B", "C", "D", "E", "F"]) setColumnWidth(checkSheet, col, 20, 13);
setColumnWidth(checkSheet, "G", 20, 48);

// 資料來源
titleBand(sources, "A1:F1", "營運動能資料來源與方法限制");
sources.getRange("A4:F4").values = [["來源ID", "資料集／項目", "資料日期", "提供者", "網址", "用途與限制"]];
formatHeader(sources.getRange("A4:F4"));
sources.getRange("A5:F8").values = [
  ["FM-MKT", "Price / PER / PBR / MarketValue", meta.latest_market_date, "FinMind", "https://finmind.github.io/tutor/TaiwanMarket/Technical/", "市場、估值與成交流動性"],
  ["FM-FUND", "Income / CashFlows / BalanceSheet", meta.latest_financial_quarter, "FinMind", "https://finmind.github.io/tutor/TaiwanMarket/Fundamental/", "獲利、營益率、現金轉換與財務品質"],
  ["FM-REV", "TaiwanStockMonthRevenue", meta.latest_revenue_period, "FinMind", "https://finmind.github.io/tutor/TaiwanMarket/Fundamental/", "近月營收年增與前後三月動能差"],
  ["MODEL", "高品質營運動能模型", meta.as_of, "本專案", "", "營運60／品質25／估值流動性15；不構成投資建議"],
];
sources.getRange("A10:F14").values = [
  ["完整明細", "screening_results.csv", meta.as_of, "本專案", "", `Excel 主排名只保留硬門檻通過欄位；全市場 33 欄請查 reports/momentum/${meta.as_of}/screening_results.csv`],
  ["限制", "低基期與轉盈", "", "", "", "前期淨利非正者不與一般成長公司混合排名"],
  ["限制", "月營收", "", "", "", "月營收不等於獲利；須搭配營益率與現金流"],
  ["限制", "資料時點", "", "", "", "市場每日、營收每月、財報每季更新，頻率不同"],
  ["限制", "治理與成長來源", "", "", "", "必須以年報、法說及公開資訊人工查證"],
];
sources.getRange("E5:E7").format.font = { color: colors.red };
setColumnWidth(sources, "A", 14, 12);
setColumnWidth(sources, "B", 14, 34);
setColumnWidth(sources, "C", 14, 16);
setColumnWidth(sources, "D", 14, 14);
setColumnWidth(sources, "E", 14, 58);
setColumnWidth(sources, "F", 14, 52);
sources.freezePanes.freezeRows(4);

workbook.comments.setSelf({ displayName: "pump" });
workbook.comments.addThread({ cell: ranking.getRange("H5") }, "市場資料來源：https://finmind.github.io/tutor/TaiwanMarket/Technical/");
workbook.comments.addThread({ cell: ranking.getRange("L5") }, "營收與財報資料來源：https://finmind.github.io/tutor/TaiwanMarket/Fundamental/");

// 代表性分數需與Python模型一致。
for (let index = 0; index < auditRows.length; index += 1) {
  const rowNumber = auditFirstDataRow + index;
  const calculated = audit.getRange(`AA${rowNumber}:AD${rowNumber}`).values[0];
  const expected = [
    auditRows[index].operating_momentum_score,
    auditRows[index].quality_score,
    auditRows[index].valuation_liquidity_score,
    auditRows[index].total_score,
  ];
  for (let column = 0; column < 4; column += 1) {
    const actual = Number(calculated[column]);
    if (!Number.isFinite(actual) || Math.abs(actual - Number(expected[column])) > 0.01) {
      throw new Error(`Momentum score audit mismatch at audit row ${rowNumber}, component ${column}`);
    }
  }
}
console.log("[QA] representative momentum formulas tie to pipeline");

const dashboardCheck = await workbook.inspect({
  kind: "table", range: "儀表板!A1:Q34", include: "values,formulas", tableMaxRows: 34, tableMaxCols: 17, maxChars: 7000,
});
console.log("[QA] momentum dashboard", dashboardCheck.ndjson);
const explanationCheck = await workbook.inspect({
  kind: "table", range: "模型說明!A1:H28", include: "values,formulas", tableMaxRows: 28, tableMaxCols: 8, maxChars: 7000,
});
console.log("[QA] momentum explanation", explanationCheck.ndjson);
const rankingCheck = await workbook.inspect({
  kind: "table", range: `動能排名!A1:Y${Math.min(rankingLastRow, 12)}`, include: "values,formulas", tableMaxRows: 12, tableMaxCols: 25, maxChars: 9000,
});
console.log("[QA] momentum ranking", rankingCheck.ndjson);
const rejectedCheck = await workbook.inspect({
  kind: "table", range: `未通過明細!A1:F${Math.min(rejectedLastRow, 12)}`, include: "values,formulas", tableMaxRows: 12, tableMaxCols: 6, maxChars: 5000,
});
console.log("[QA] momentum rejected", rejectedCheck.ndjson);
const auditCheck = await workbook.inspect({
  kind: "table", range: `試算稽核!A1:AG${auditLastRow}`, include: "values,formulas", tableMaxRows: auditLastRow, tableMaxCols: 33, maxChars: 10000,
});
console.log("[QA] momentum formula audit", auditCheck.ndjson);
const reviewCheck = await workbook.inspect({
  kind: "table", range: `人工複核!A1:L${Math.min(5 + focusRows.length, 12)}`, include: "values,formulas", tableMaxRows: 12, tableMaxCols: 12, maxChars: 7000,
});
console.log("[QA] momentum review", reviewCheck.ndjson);
const errors = await workbook.inspect({
  kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 300 }, summary: "final formula error scan", maxChars: 5000,
});
console.log("[QA] momentum errors", errors.ndjson);

const qaDir = path.join(root, "qa", meta.as_of, "momentum");
await fs.mkdir(qaDir, { recursive: true });
const renderSpecs = [
  ["儀表板", "A1:Q34", "dashboard.png"],
  ["模型說明", "A1:H28", "model_explanation.png"],
  ["動能排名", `A1:Y${Math.min(rankingLastRow, 16)}`, "ranking.png"],
  ["未通過明細", `A1:F${Math.min(rejectedLastRow, 16)}`, "rejected.png"],
  ["試算稽核", `A1:R${auditLastRow}`, "audit_left.png"],
  ["試算稽核", `S1:AG${auditLastRow}`, "audit_right.png"],
  ["人工複核", `A1:L${Math.max(12, 5 + focusRows.length)}`, "manual_review.png"],
  ["參數", "A1:E34", "assumptions.png"],
  ["檢核", `A1:G${5 + checks.length}`, "checks.png"],
  ["資料來源", "A1:F14", "sources.png"],
];
for (const [sheetName, range, fileName] of renderSpecs) {
  const preview = await workbook.render({ sheetName, range, scale: 1, format: "png" });
  await fs.writeFile(path.join(qaDir, fileName), new Uint8Array(await preview.arrayBuffer()));
}

await fs.mkdir(path.dirname(outputPath), { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
await moveInspectSidecar(outputPath, qaDir);
console.log(`[完成] 營運動能Excel: ${outputPath}`);
