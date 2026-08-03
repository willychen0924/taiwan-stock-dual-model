#!/usr/bin/env node
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";


const inputPath = process.argv[2] ?? "reports/latest/screening_results.json";
const outputPath = process.argv[3] ?? "outputs/latest/台股價值篩選.xlsx";
const root = process.cwd();
const payload = JSON.parse(await fs.readFile(inputPath, "utf8"));
const { metadata: meta, config, checks, results } = payload;

const workbook = Workbook.create();
const dashboard = workbook.worksheets.add("儀表板");
const explanation = workbook.worksheets.add("模型說明");
const ranking = workbook.worksheets.add("量化排名");
const review = workbook.worksheets.add("人工複核");
const assumptions = workbook.worksheets.add("參數");
const checkSheet = workbook.worksheets.add("檢核");
const sources = workbook.worksheets.add("資料來源");

const colors = {
  navy: "#12263F",
  teal: "#0F766E",
  lightTeal: "#DDF4EF",
  blue: "#0000FF",
  green: "#008000",
  red: "#FF0000",
  yellow: "#FFF2CC",
  lightBlue: "#EAF1F8",
  lightGray: "#EEF2F6",
  gray: "#64748B",
  white: "#FFFFFF",
  black: "#000000",
};

for (const sheet of [dashboard, explanation, ranking, review, assumptions, checkSheet, sources]) {
  sheet.showGridLines = false;
}

function titleBand(sheet, range, text) {
  sheet.getRange(range).merge();
  const cell = sheet.getRange(range.split(":")[0]);
  cell.values = [[text]];
  cell.format = {
    fill: colors.navy,
    font: { bold: true, color: colors.white, size: 18 },
    verticalAlignment: "center",
  };
  sheet.getRange(range).format.rowHeight = 34;
}

function formatHeader(range) {
  range.format = {
    fill: colors.navy,
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

function linearFormula(cell, floorRef, targetRef, points) {
  return `IF(OR(${cell}="",NOT(ISNUMBER(${cell}))),0,${points}*MAX(0,MIN(1,(${cell}-${floorRef})/(${targetRef}-${floorRef}))))`;
}

function descendingFormula(cell, bestRef, worstRef, points) {
  return `IF(OR(${cell}="",NOT(ISNUMBER(${cell}))),0,${points}*MAX(0,MIN(1,(${worstRef}-${cell})/(${worstRef}-${bestRef}))))`;
}

// 模型說明
titleBand(explanation, "A1:H1", "防禦型價值模型說明");
explanation.getRange("A3:H3").merge();
explanation.getRange("A3").values = [["核心概念"]];
explanation.getRange("A3:H3").format = { fill: colors.teal, font: { bold: true, color: colors.white, size: 12 } };
explanation.getRange("A4:H8").merge();
explanation.getRange("A4").values = [["這套模型不是直接挑選最便宜的股票，而是先排除明顯風險，再比較財務體質、估值與營運動能。模型先以獲利、現金流、負債與成交量建立安全底線，再從防禦能力、估值合理性及營運動能三方面評分。\n\n量化排名只用來縮小研究範圍，不代表預期報酬或買進建議；公司治理、競爭優勢與新動能仍須透過年報、法說及公開資訊查證。"]];
explanation.getRange("A4:H8").format = { fill: colors.lightBlue, font: { color: colors.black, size: 11 }, wrapText: true, verticalAlignment: "center" };
explanation.getRange("A10:H10").merge();
explanation.getRange("A10").values = [["篩選流程"]];
explanation.getRange("A10:H10").format = { fill: colors.teal, font: { bold: true, color: colors.white, size: 12 } };
const valueModelSteps = [
  ["1 建立母體", "納入上市、上櫃四位數普通股，排除ETF、存託憑證；金融業因財務結構不同，不與一般公司混合評分。"],
  ["2 硬門檻", "要求約十年交易歷史、五年持續獲利、至少三年正自由現金流、TTM淨利為正，並符合負債與20日均成交額5,000萬元門檻。"],
  ["3 防禦50分", "檢視淨現金、流動比率、負債程度、獲利穩定性與自由現金流，評估財務下檔承受能力。"],
  ["4 估值30分", "比較保守清算價值、同業PER／PBR分位及絕對本益比，避免只看單一估值指標。"],
  ["5 動能20分", "觀察近三月與單月營收年增率、同業營益率位置及TTM淨利成長。"],
  ["6 研究漏斗", "通過硬門檻後依總分排序，前100名列入觀察名單，前20名列為優先質化研究對象。"],
  ["7 人工覆核", "確認公司治理、經營誠信、競爭優勢、新動能與重大風險；模型短評不取代人工查證。"],
];
valueModelSteps.forEach(([label, description], index) => {
  const row = 12 + index * 2;
  explanation.getRange(`A${row}:B${row + 1}`).merge();
  explanation.getRange(`C${row}:H${row + 1}`).merge();
  explanation.getRange(`A${row}`).values = [[label]];
  explanation.getRange(`C${row}`).values = [[description]];
  explanation.getRange(`A${row}:B${row + 1}`).format = { fill: index % 2 ? colors.lightGray : colors.lightTeal, font: { bold: true, color: colors.navy }, verticalAlignment: "center" };
  explanation.getRange(`C${row}:H${row + 1}`).format = { fill: index % 2 ? "#F8FAFC" : "#F0FDFA", wrapText: true, verticalAlignment: "center" };
  explanation.getRange(`A${row}:H${row + 1}`).format.borders = { preset: "outside", style: "thin", color: "#CBD5E1" };
});
for (const col of ["A", "B"]) setColumnWidth(explanation, col, 26, 13);
for (const col of ["C", "D", "E", "F", "G", "H"]) setColumnWidth(explanation, col, 26, 16);
explanation.getRange("A4:H8").format.rowHeight = 25;

// 參數
titleBand(assumptions, "A1:E1", "模型參數與評分假設");
assumptions.getRange("A2:E2").merge();
assumptions.getRange("A2").values = [["藍字為可調整參數；綠字為跨工作表公式；修改門檻後請重新執行掃描以重排名次。"]];
assumptions.getRange("A2").format = { font: { color: colors.gray, italic: true }, wrapText: true };
assumptions.getRange("A4:E4").values = [["類別", "參數", "數值", "單位", "說明"]];
formatHeader(assumptions.getRange("A4:E4"));

const paramRows = [
  ["清算折價", "現金", config.liquidation_haircuts.cash, "比例", "現金及約當現金"],
  ["清算折價", "流動金融資產", config.liquidation_haircuts.current_financial_assets, "比例", "流動金融資產折價"],
  ["清算折價", "應收款", config.liquidation_haircuts.receivables, "比例", "保守回收率"],
  ["清算折價", "存貨", config.liquidation_haircuts.inventory, "比例", "保守變現率"],
  ["清算折價", "不動產廠房設備", config.liquidation_haircuts.property_plant_equipment, "比例", "帳面價值折價"],
  ["清算折價", "商譽", config.liquidation_haircuts.goodwill, "比例", "預設不計清算價值"],
];
assumptions.getRange("A5:E10").values = paramRows;
assumptions.getRange("A12:E12").merge();
assumptions.getRange("A12").values = [["硬性門檻"]];
assumptions.getRange("A12:E12").format = { fill: colors.teal, font: { bold: true, color: colors.white } };
const gateRows = [
  ["硬門檻", "至少交易歷史", config.hard_gates.required_history_years, "年", "以十年前附近是否有成交資料近似"],
  ["硬門檻", "五年獲利年數", config.hard_gates.min_profitable_years, "年", "每年四季完整且淨利為正"],
  ["硬門檻", "完整獲利資料年數", config.hard_gates.min_complete_profit_years, "年", "避免資料缺漏誤判"],
  ["硬門檻", "正自由現金流年數", config.hard_gates.min_positive_fcf_years, "年", "CFO－資本支出"],
  ["硬門檻", "最低流動比率", config.hard_gates.min_current_ratio, "倍", "金融業不適用"],
  ["硬門檻", "最高負債／資產", config.hard_gates.max_liabilities_to_assets, "比例", "金融業不適用"],
  ["硬門檻", "最高有息負債／現金", config.hard_gates.max_debt_to_cash, "倍", "偏好淨現金或低負債"],
  ["硬門檻", "最低20日均成交金額", config.hard_gates.min_avg_daily_turnover_twd, "TWD", "集中策略仍需流動性"],
  ["硬門檻", "要求TTM淨利為正", config.hard_gates.require_positive_ttm_income ? 1 : 0, "0/1", "1代表啟用"],
  ["模型", "歷史分析年數", meta.annual_years.length, "年", meta.annual_years.join("、")],
];
assumptions.getRange("A13:E22").values = gateRows;
assumptions.getRange("A24:E24").merge();
assumptions.getRange("A24").values = [["線性評分端點"]];
assumptions.getRange("A24:E24").format = { fill: colors.teal, font: { bold: true, color: colors.white } };
const targetRows = [
  ["評分", "淨現金／市值下限", config.score_targets.net_cash_ratio_floor, "比例", "低於此值得0分"],
  ["評分", "淨現金／市值滿分", config.score_targets.net_cash_ratio_target, "比例", "達此值取得該項滿分"],
  ["評分", "流動比率下限", config.score_targets.current_ratio_floor, "倍", "低於此值得0分"],
  ["評分", "流動比率滿分", config.score_targets.current_ratio_target, "倍", "達此值取得該項滿分"],
  ["評分", "負債比率滿分", config.score_targets.liabilities_ratio_target, "比例", "越低越好"],
  ["評分", "負債比率最差", config.score_targets.liabilities_ratio_worst, "比例", "達此值得0分"],
  ["評分", "清算覆蓋下限", config.score_targets.liquidation_coverage_floor, "比例", "低於此值得0分"],
  ["評分", "清算覆蓋滿分", config.score_targets.liquidation_coverage_target, "比例", "清算價值／市值"],
  ["評分", "PER最佳端", config.score_targets.per_best, "倍", "低PER端"],
  ["評分", "PER最差端", config.score_targets.per_worst, "倍", "高PER端"],
  ["評分", "成長率下限", config.score_targets.growth_floor, "比例", "低於此值得0分"],
  ["評分", "成長率滿分", config.score_targets.growth_target, "比例", "達此值取得該項滿分"],
];
assumptions.getRange("A25:E36").values = targetRows;
assumptions.getRange("A38:E38").merge();
assumptions.getRange("A38").values = [["權重"]];
assumptions.getRange("A38:E38").format = { fill: colors.teal, font: { bold: true, color: colors.white } };
assumptions.getRange("A39:E41").values = [
  ["權重", "防禦", config.weights.defense, "分", "淨現金、流動性、負債、獲利、FCF"],
  ["權重", "估值", config.weights.valuation, "分", "清算覆蓋、同業估值與絕對PER"],
  ["權重", "動能", config.weights.momentum, "分", "營收、獲利與同業營益率"],
];
assumptions.getRange("A42:B42").merge();
assumptions.getRange("A42").values = [["權重合計"]];
assumptions.getRange("C42").formulas = [["=SUM(C39:C41)"]];
assumptions.getRange("C5:C41").format.font = { color: colors.blue };
assumptions.getRange("C5:C41").format.fill = colors.yellow;
assumptions.getRange("C5:C10").format.numberFormat = "0%";
assumptions.getRange("C17").format.numberFormat = "0.00x";
assumptions.getRange("C18").format.numberFormat = "0.0%";
assumptions.getRange("C25:C26").format.numberFormat = "0.0%";
assumptions.getRange("C29:C32").format.numberFormat = "0.0%";
assumptions.getRange("C35:C36").format.numberFormat = "0.0%";
assumptions.getRange("A44:E47").values = [
  ["圖例", "藍字", "可調整輸入", "", ""],
  ["圖例", "黑字", "本表公式／計算", "", ""],
  ["圖例", "綠字", "跨工作表引用", "", ""],
  ["圖例", "紅字", "外部來源連結", "", ""],
];
assumptions.getRange("B44").format.font = { color: colors.blue };
assumptions.getRange("B45").format.font = { color: colors.black };
assumptions.getRange("B46").format.font = { color: colors.green };
assumptions.getRange("B47").format.font = { color: colors.red };
assumptions.getRange("A4:E47").format.font.size = 10;
assumptions.getRange("A4:E47").format.wrapText = true;
setColumnWidth(assumptions, "A", 47, 14);
setColumnWidth(assumptions, "B", 47, 25);
setColumnWidth(assumptions, "C", 47, 16);
setColumnWidth(assumptions, "D", 47, 12);
setColumnWidth(assumptions, "E", 47, 48);
assumptions.freezePanes.freezeRows(4);

// 全市場排名
titleBand(ranking, "A1:AS1", "台股全市場量化排名");
ranking.getRange("A2:AS2").merge();
ranking.getRange("A2").values = [[`市場資料 ${meta.latest_market_date}｜完整財報季 ${meta.latest_financial_quarter}｜一般公司模型；金融業僅列示、不混合評分。`]];
ranking.getRange("A2").format = { fill: colors.lightBlue, font: { color: colors.gray }, wrapText: true };
ranking.getRange("A3:AS3").merge();
ranking.getRange("A3").values = [["排名順序依本次掃描結果固定；調整參數可即時重算分數，但須重新執行掃描才會重新排序。"]];
ranking.getRange("A3").format = { font: { italic: true, color: colors.gray } };

const headers = [
  "排名", "代碼", "公司", "產業", "市場", "漏斗階段", "治理狀態", "未通過原因", "收盤價", "市值",
  "20日均成交額", "PER", "PBR", "現金", "有息負債", "流動資產", "流動負債", "總負債", "總資產", "應收款",
  "存貨", "流動金融資產", "不動產廠房設備", "淨現金/市值", "流動比率", "負債/資產", "負債/現金", "保守清算價值", "清算覆蓋", "獲利年數",
  "完整獲利年數", "正FCF年數", "近3月營收YoY", "單月營收YoY", "TTM營益率", "TTM淨利成長", "同業PER分位", "同業PBR分位", "同業營益率分位", "防禦分",
  "估值分", "動能分", "總分", "硬門檻", "缺漏旗標",
];
ranking.getRange("A5:AS5").values = [headers];
formatHeader(ranking.getRange("A5:AS5"));
ranking.getRange("A5:AS5").format.rowHeight = 44;

const rankingRows = results.map((row) => [
  row.rank, row.stock_id, row.stock_name, row.industry, row.market, row.funnel_stage, row.governance_status,
  row.exclusion_reasons, row.close, row.market_value, row.avg_daily_turnover, row.per, row.pbr, row.cash, row.debt,
  row.current_assets, row.current_liabilities, row.liabilities, row.total_assets, row.receivables, row.inventory,
  row.current_financial_assets, row.property_plant_equipment, null, null, null, null, null, null, row.profitable_years,
  row.complete_profit_years, row.positive_fcf_years, row.revenue_3m_yoy, row.latest_revenue_yoy, row.ttm_operating_margin,
  row.ttm_net_income_growth, row.sector_per_percentile, row.sector_pbr_percentile, row.sector_margin_percentile,
  null, null, null, null, row.hard_pass, row.missing_flags,
]);
const firstDataRow = 6;
const lastDataRow = firstDataRow + rankingRows.length - 1;
if (rankingRows.length) {
  ranking.getRange(`A${firstDataRow}:AS${lastDataRow}`).values = rankingRows;
  const formulaRows = results.map((_, index) => firstDataRow + index);
  ranking.getRange(`X${firstDataRow}:X${lastDataRow}`).formulas = formulaRows.map((r) => [`=IFERROR((N${r}-O${r})/J${r},0)`]);
  ranking.getRange(`Y${firstDataRow}:Y${lastDataRow}`).formulas = formulaRows.map((r) => [`=IFERROR(P${r}/Q${r},0)`]);
  ranking.getRange(`Z${firstDataRow}:Z${lastDataRow}`).formulas = formulaRows.map((r) => [`=IFERROR(R${r}/S${r},0)`]);
  ranking.getRange(`AA${firstDataRow}:AA${lastDataRow}`).formulas = formulaRows.map((r) => [`=IFERROR(O${r}/N${r},999)`]);
  ranking.getRange(`AB${firstDataRow}:AB${lastDataRow}`).formulas = formulaRows.map((r) => [
    `=N${r}*'參數'!$C$5+V${r}*'參數'!$C$6+T${r}*'參數'!$C$7+U${r}*'參數'!$C$8+W${r}*'參數'!$C$9-R${r}`,
  ]);
  ranking.getRange(`AC${firstDataRow}:AC${lastDataRow}`).formulas = formulaRows.map((r) => [`=IFERROR(AB${r}/J${r},0)`]);
  ranking.getRange(`AN${firstDataRow}:AN${lastDataRow}`).formulas = formulaRows.map((r) => [
    `=${linearFormula(`X${r}`, "'參數'!$C$25", "'參數'!$C$26", 15)}+${linearFormula(`Y${r}`, "'參數'!$C$27", "'參數'!$C$28", 10)}+${descendingFormula(`Z${r}`, "'參數'!$C$29", "'參數'!$C$30", 10)}+10*MAX(0,MIN(1,AD${r}/'參數'!$C$14))+5*MAX(0,MIN(1,AF${r}/'參數'!$C$22))`,
  ]);
  ranking.getRange(`AO${firstDataRow}:AO${lastDataRow}`).formulas = formulaRows.map((r) => [
    `=${linearFormula(`AC${r}`, "'參數'!$C$31", "'參數'!$C$32", 12)}+IFERROR(10*(1-AK${r}),0)+IFERROR(4*(1-AL${r}),0)+${descendingFormula(`L${r}`, "'參數'!$C$33", "'參數'!$C$34", 4)}`,
  ]);
  ranking.getRange(`AP${firstDataRow}:AP${lastDataRow}`).formulas = formulaRows.map((r) => [
    `=${linearFormula(`AG${r}`, "'參數'!$C$35", "'參數'!$C$36", 8)}+${linearFormula(`AH${r}`, "'參數'!$C$35", "'參數'!$C$36", 4)}+IFERROR(4*AM${r},0)+${linearFormula(`AJ${r}`, "'參數'!$C$35", "'參數'!$C$36", 4)}`,
  ]);
  ranking.getRange(`AQ${firstDataRow}:AQ${lastDataRow}`).formulas = formulaRows.map((r) => [`=SUM(AN${r}:AP${r})`]);
  ranking.getRange(`A${firstDataRow}:AS${lastDataRow}`).format.font.size = 9;
  ranking.getRange(`B${firstDataRow}:H${lastDataRow}`).format.horizontalAlignment = "left";
  ranking.getRange(`I${firstDataRow}:AQ${lastDataRow}`).format.horizontalAlignment = "right";
  ranking.getRange(`I${firstDataRow}:I${lastDataRow}`).format.numberFormat = "#,##0.00;[Red](#,##0.00);-";
  ranking.getRange(`J${firstDataRow}:W${lastDataRow}`).format.numberFormat = "#,##0;[Red](#,##0);-";
  ranking.getRange(`L${firstDataRow}:M${lastDataRow}`).format.numberFormat = "0.0x;[Red](0.0x);-";
  ranking.getRange(`X${firstDataRow}:X${lastDataRow}`).format.numberFormat = "0.0%;[Red](0.0%);-";
  ranking.getRange(`Y${firstDataRow}:Y${lastDataRow}`).format.numberFormat = "0.00x;[Red](0.00x);-";
  ranking.getRange(`Z${firstDataRow}:Z${lastDataRow}`).format.numberFormat = "0.0%;[Red](0.0%);-";
  ranking.getRange(`AA${firstDataRow}:AA${lastDataRow}`).format.numberFormat = "0.00x;[Red](0.00x);-";
  ranking.getRange(`AB${firstDataRow}:AB${lastDataRow}`).format.numberFormat = "#,##0;[Red](#,##0);-";
  ranking.getRange(`AC${firstDataRow}:AC${lastDataRow}`).format.numberFormat = "0.0%;[Red](0.0%);-";
  ranking.getRange(`AG${firstDataRow}:AM${lastDataRow}`).format.numberFormat = "0.0%;[Red](0.0%);-";
  ranking.getRange(`AN${firstDataRow}:AQ${lastDataRow}`).format.numberFormat = "0.0";
  ranking.getRange(`AN${firstDataRow}:AQ${lastDataRow}`).format.font = { color: colors.green };
  ranking.getRange(`AQ${firstDataRow}:AQ${lastDataRow}`).conditionalFormats.add("colorScale", {
    criteria: [
      { type: "lowestValue", color: "#FEE2E2" },
      { type: "percentile", value: 50, color: "#FEF3C7" },
      { type: "highestValue", color: "#DCFCE7" },
    ],
  });
  const table = ranking.tables.add(`A5:AS${lastDataRow}`, true, "MarketRankingTable");
  table.style = "TableStyleMedium2";
}
ranking.freezePanes.freezeRows(5);
ranking.freezePanes.freezeColumns(3);
setColumnWidth(ranking, "A", lastDataRow, 8);
setColumnWidth(ranking, "B", lastDataRow, 9);
setColumnWidth(ranking, "C", lastDataRow, 14);
setColumnWidth(ranking, "D", lastDataRow, 15);
setColumnWidth(ranking, "E", lastDataRow, 8);
setColumnWidth(ranking, "F", lastDataRow, 12);
setColumnWidth(ranking, "G", lastDataRow, 12);
setColumnWidth(ranking, "H", lastDataRow, 36);
for (const col of ["I", "L", "M", "X", "Y", "Z", "AA", "AC", "AD", "AE", "AF", "AG", "AH", "AI", "AJ", "AK", "AL", "AM", "AN", "AO", "AP", "AQ", "AR"]) {
  setColumnWidth(ranking, col, lastDataRow, 12);
}
for (const col of ["J", "K", "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "AB"]) {
  setColumnWidth(ranking, col, lastDataRow, 16);
}
setColumnWidth(ranking, "AS", lastDataRow, 18);

// 儀表板
titleBand(dashboard, "A1:Q1", "台股防禦型價值篩選儀表板");
dashboard.getRange("A2:Q2").merge();
dashboard.getRange("A2").values = [[`資料日 ${meta.latest_market_date}｜財報季 ${meta.latest_financial_quarter}｜營收期 ${meta.latest_revenue_period}｜僅供研究篩選，非投資建議`]];
dashboard.getRange("A2").format = { fill: colors.lightBlue, font: { color: colors.gray }, horizontalAlignment: "left" };
const cards = [
  ["普通股母體", meta.universe_count],
  ["一般公司模型", meta.operating_company_count],
  ["硬門檻通過", meta.hard_pass_count],
  ["自選100", meta.watchlist_count],
  ["精華20", meta.focus_count],
];
cards.forEach(([label, value], index) => {
  const startCol = 1 + index * 2;
  const labelRange = dashboard.getRangeByIndexes(3, startCol - 1, 1, 2);
  const valueRange = dashboard.getRangeByIndexes(4, startCol - 1, 1, 2);
  labelRange.merge();
  valueRange.merge();
  labelRange.values = [[label]];
  valueRange.values = [[value]];
  labelRange.format = { fill: colors.lightGray, font: { color: colors.gray, bold: true }, horizontalAlignment: "center" };
  valueRange.format = { fill: colors.white, font: { color: colors.teal, bold: true, size: 18 }, horizontalAlignment: "center", borders: { preset: "outside", style: "thin", color: "#CBD5E1" } };
});
dashboard.getRange("L4:M4").merge();
dashboard.getRange("L4").values = [["模型狀態"]];
dashboard.getRange("L4:M4").format = { fill: colors.lightGray, font: { color: colors.gray, bold: true }, horizontalAlignment: "center" };
dashboard.getRange("L5:M5").merge();
dashboard.getRange("L5").formulas = [["='檢核'!B2"]];
dashboard.getRange("L5:M5").format = { font: { color: colors.green, bold: true, size: 16 }, horizontalAlignment: "center", borders: { preset: "outside", style: "thin", color: "#CBD5E1" } };

dashboard.getRange("A7:H7").merge();
dashboard.getRange("A7").values = [["精華候選（仍需治理、護城河與新動能質化複核）"]];
dashboard.getRange("A7:H7").format = { fill: colors.teal, font: { bold: true, color: colors.white } };
dashboard.getRange("A8:H8").values = [["排名", "代碼", "公司", "產業", "防禦", "估值", "動能", "總分"]];
formatHeader(dashboard.getRange("A8:H8"));
const focusSize = Math.min(config.report.focus_size, meta.hard_pass_count);
const dashboardFormulaRows = [];
for (let i = 0; i < config.report.focus_size; i += 1) {
  const sourceRow = firstDataRow + i;
  dashboardFormulaRows.push([
    `=IF('量化排名'!$AR$${sourceRow},'量化排名'!A${sourceRow},"")`,
    `=IF('量化排名'!$AR$${sourceRow},'量化排名'!B${sourceRow},"")`,
    `=IF('量化排名'!$AR$${sourceRow},'量化排名'!C${sourceRow},"")`,
    `=IF('量化排名'!$AR$${sourceRow},'量化排名'!D${sourceRow},"")`,
    `=IF('量化排名'!$AR$${sourceRow},'量化排名'!AN${sourceRow},"")`,
    `=IF('量化排名'!$AR$${sourceRow},'量化排名'!AO${sourceRow},"")`,
    `=IF('量化排名'!$AR$${sourceRow},'量化排名'!AP${sourceRow},"")`,
    `=IF('量化排名'!$AR$${sourceRow},'量化排名'!AQ${sourceRow},"")`,
  ]);
}
dashboard.getRange(`A9:H${8 + config.report.focus_size}`).formulas = dashboardFormulaRows;
dashboard.getRange(`A9:H${8 + config.report.focus_size}`).format.font = { color: colors.green, size: 10 };
dashboard.getRange(`E9:H${8 + config.report.focus_size}`).format.numberFormat = "0.0";
dashboard.getRange(`A8:H${8 + config.report.focus_size}`).format.borders = { preset: "outside", style: "thin", color: "#CBD5E1" };
dashboard.getRange("J22:K22").values = [["公司", "總分"]];
formatHeader(dashboard.getRange("J22:K22"));
const chartFormulas = [];
for (let i = 0; i < 10; i += 1) {
  const dashboardRow = 9 + i;
  chartFormulas.push([`=B${dashboardRow}&" "&C${dashboardRow}`, `=H${dashboardRow}`]);
}
dashboard.getRange("J23:K32").formulas = chartFormulas;
dashboard.getRange("J23:K32").format.font = { color: colors.green, size: 9 };
dashboard.getRange("K23:K32").format.numberFormat = "0.0";
const scoreChart = dashboard.charts.add("bar", dashboard.getRange("J22:K32"));
scoreChart.title = "Top 10 綜合分數（100分）";
scoreChart.titleTextStyle.fontSize = 12;
scoreChart.hasLegend = false;
scoreChart.yAxis = { numberFormatCode: "0.0", min: 0, max: 100 };
scoreChart.setPosition("J7", "Q20");
dashboard.getRange("J34:Q36").merge();
dashboard.getRange("J34").values = [["量化分數僅是研究漏斗。治理誠信、競爭優勢及新技術催化未通過質化複核前，不應視為集中持股候選。"]];
dashboard.getRange("J34:Q36").format = { fill: colors.yellow, font: { color: "#7C2D12" }, wrapText: true, verticalAlignment: "center" };
dashboard.freezePanes.freezeRows(2);
for (const col of ["A", "E", "F", "G", "H"]) setColumnWidth(dashboard, col, 36, 11);
setColumnWidth(dashboard, "B", 36, 10);
setColumnWidth(dashboard, "C", 36, 14);
setColumnWidth(dashboard, "D", 36, 15);
setColumnWidth(dashboard, "I", 36, 3);
setColumnWidth(dashboard, "J", 36, 20);
setColumnWidth(dashboard, "K", 36, 13);
for (const col of ["L", "M", "N", "O", "P", "Q"]) setColumnWidth(dashboard, col, 36, 12);

// 人工複核
titleBand(review, "A1:L1", "精華 20 人工質化複核");
review.getRange("A2:L2").merge();
review.getRange("A2").values = [["模型短評由量化欄位自動產生；黃色藍字欄位可編輯，但要永久保存請同步更新 config/manual_review.csv。治理誠信是否決條件，不以高分抵銷。"]];
review.getRange("A2").format = { fill: colors.yellow, font: { color: "#7C2D12" }, wrapText: true };
review.getRange("A5:L5").values = [["排名", "代碼", "公司", "產業", "總分", "治理狀態", "新動能／催化", "人工排除", "複核筆記", "模型短評（自動）", "量化狀態", "質化結論"]];
formatHeader(review.getRange("A5:L5"));
const focusRows = results.filter((row) => row.hard_pass).slice(0, config.report.focus_size);
if (focusRows.length) {
  const reviewValues = focusRows.map((row) => [
    row.rank, row.stock_id, row.stock_name, row.industry, row.total_score, row.governance_status,
    row.catalyst, row.manual_exclude ? "是" : "否", row.manual_notes, row.model_summary, "量化硬門檻通過", null,
  ]);
  const reviewLastRow = 5 + reviewValues.length;
  review.getRange(`A6:L${reviewLastRow}`).values = reviewValues;
  review.getRange(`L6:L${reviewLastRow}`).formulas = focusRows.map((_, index) => {
    const r = 6 + index;
    return [`=IF(F${r}="否決","排除",IF(AND(F${r}="通過",G${r}<>""),"可進深度研究","待完成質化"))`];
  });
  review.getRange(`E6:E${reviewLastRow}`).format.numberFormat = "0.0";
  review.getRange(`F6:I${reviewLastRow}`).format = { fill: colors.yellow, font: { color: colors.blue }, wrapText: true };
  review.getRange(`J6:J${reviewLastRow}`).format = { fill: colors.lightBlue, font: { color: colors.black }, wrapText: true, verticalAlignment: "center" };
  review.getRange(`J6:J${reviewLastRow}`).format.rowHeight = 38;
  review.getRange(`L6:L${reviewLastRow}`).format.font = { color: colors.black, bold: true };
  review.getRange(`F6:F${reviewLastRow}`).dataValidation = { rule: { type: "list", values: ["待複核", "通過", "否決"] } };
  review.getRange(`H6:H${reviewLastRow}`).dataValidation = { rule: { type: "list", values: ["否", "是"] } };
  review.getRange(`A5:L${reviewLastRow}`).format.borders = { preset: "outside", style: "thin", color: "#CBD5E1" };
}
review.freezePanes.freezeRows(5);
const reviewWidths = { A: 8, B: 9, C: 14, D: 15, E: 10, F: 13, G: 26, H: 12, I: 30, J: 52, K: 18, L: 18 };
for (const [col, width] of Object.entries(reviewWidths)) setColumnWidth(review, col, 30, width);

// 檢核
titleBand(checkSheet, "A1:G1", "模型檢核");
checkSheet.getRange("A2").values = [["整體狀態"]];
checkSheet.getRange("B2").formulas = [[`=IF(COUNTIF(F6:F${5 + checks.length},"FAIL")>0,"FAIL",IF(COUNTIF(F6:F${5 + checks.length},"WARN")>0,"WARN","OK"))`]];
checkSheet.getRange("A2:B2").format = { fill: colors.lightBlue, font: { bold: true }, borders: { preset: "outside", style: "thin", color: "#CBD5E1" } };
checkSheet.getRange("B2").format.font = { bold: true, color: colors.green };
checkSheet.getRange("A5:G5").values = [["檢核", "實際", "預期", "差異", "容忍值", "狀態", "說明"]];
formatHeader(checkSheet.getRange("A5:G5"));
const checkRows = checks.map((item) => [item.check, item.actual, item.expected, null, item.tolerance, item.status, item.notes]);
checkSheet.getRange(`A6:G${5 + checks.length}`).values = checkRows;
checkSheet.getRange(`D6:D${5 + checks.length}`).formulas = checks.map((_, index) => {
  const r = 6 + index;
  return [`=IFERROR(B${r}-C${r},0)`];
});
checkSheet.getRange(`A5:G${5 + checks.length}`).format.borders = { preset: "outside", style: "thin", color: "#CBD5E1" };
checkSheet.getRange("B7:D9").format.numberFormat = "0.0%";
setColumnWidth(checkSheet, "A", 20, 28);
for (const col of ["B", "C", "D", "E", "F"]) setColumnWidth(checkSheet, col, 20, 13);
setColumnWidth(checkSheet, "G", 20, 50);
checkSheet.getRange(`G6:G${5 + checks.length}`).format.wrapText = true;

// 資料來源
titleBand(sources, "A1:F1", "資料來源與方法限制");
sources.getRange("A4:F4").values = [["來源ID", "資料集／項目", "資料日期", "提供者", "網址", "用途與限制"]];
formatHeader(sources.getRange("A4:F4"));
const sourceRows = [
  ["FM-MKT", "TaiwanStockInfo / Price / PER / MarketValue", meta.latest_market_date, "FinMind", "https://finmind.github.io/tutor/TaiwanMarket/Technical/", "市場、價格、市值與估值；資料更新依API實際回傳"],
  ["FM-FUND", "BalanceSheet / FinancialStatements / CashFlows / MonthRevenue", meta.latest_financial_quarter, "FinMind", "https://finmind.github.io/tutor/TaiwanMarket/Fundamental/", "財報與月營收；使用保守申報落後期"],
  ["FM-API", "FinMind API v4", meta.as_of, "FinMind", "https://api.finmindtrade.com/docs", "Backer 全市場指定日期查詢"],
  ["MODEL", "防禦型價值篩選模型", meta.as_of, "本專案", "", "商譽清算價值為0；金融業不使用一般公司模型；分數不構成投資建議"],
];
sources.getRange("A5:F8").values = sourceRows;
sources.getRange("E5:E8").format.font = { color: colors.red };
sources.getRange("A4:F8").format.borders = { preset: "outside", style: "thin", color: "#CBD5E1" };
sources.getRange("A10:F13").values = [
  ["限制", "上市年資", "", "", "", "以十年前附近有無成交資料近似，不等同正式掛牌日"],
  ["限制", "有息負債", "", "", "", "依XBRL借款、公司債、租賃負債標籤聚合，需定期稽核新標籤"],
  ["限制", "清算價值", "", "", "", "只是折價情境，不是可實現售價或股價保證"],
  ["限制", "治理與題材", "", "", "", "必須以年報、法說及公開資訊人工查證；不由FinMind分數取代"],
];
sources.getRange("A10:F13").format = { fill: colors.lightGray, wrapText: true };
setColumnWidth(sources, "A", 15, 14);
setColumnWidth(sources, "B", 15, 40);
setColumnWidth(sources, "C", 15, 18);
setColumnWidth(sources, "D", 15, 14);
setColumnWidth(sources, "E", 15, 52);
setColumnWidth(sources, "F", 15, 55);
sources.freezePanes.freezeRows(4);

// 來源註解（原始資料欄位以標題註解指向來源，避免逐列重複長網址）
workbook.comments.setSelf({ displayName: "pump" });
workbook.comments.addThread({ cell: ranking.getRange("I5") }, "FM-MKT：價格、市值與估值資料來自 https://finmind.github.io/tutor/TaiwanMarket/Technical/");
workbook.comments.addThread({ cell: ranking.getRange("N5") }, "FM-FUND：財報與現金流資料來自 https://finmind.github.io/tutor/TaiwanMarket/Fundamental/");

// Finance audit: representative workbook formulas must tie to the pipeline.
const lastPassingIndex = Math.max(0, meta.hard_pass_count - 1);
for (const index of [0, Math.min(9, lastPassingIndex), Math.min(99, lastPassingIndex), Math.min(199, lastPassingIndex), lastPassingIndex]) {
  if (index < 0) continue;
  const rowNumber = firstDataRow + index;
  const calculated = ranking.getRange(`AN${rowNumber}:AQ${rowNumber}`).values[0];
  const expected = [results[index].defense_score, results[index].valuation_score, results[index].momentum_score, results[index].total_score];
  for (let column = 0; column < 4; column += 1) {
    if (Math.abs(Number(calculated[column]) - Number(expected[column])) > 0.01) {
      throw new Error(`Score audit mismatch at ranking row ${rowNumber}, component ${column}`);
    }
  }
}
console.log("[QA] representative score formulas tie to pipeline");

// Compact verification and render pass for every sheet.
const dashboardCheck = await workbook.inspect({
  kind: "table",
  range: "儀表板!A1:Q36",
  include: "values,formulas",
  tableMaxRows: 36,
  tableMaxCols: 17,
  maxChars: 7000,
});
console.log("[QA] dashboard", dashboardCheck.ndjson);
const rankingCheck = await workbook.inspect({
  kind: "table",
  range: `量化排名!A1:AS${Math.min(lastDataRow, 12)}`,
  include: "values,formulas",
  tableMaxRows: 12,
  tableMaxCols: 45,
  maxChars: 7000,
});
console.log("[QA] ranking", rankingCheck.ndjson);
const explanationCheck = await workbook.inspect({
  kind: "table",
  range: "模型說明!A1:H26",
  include: "values,formulas",
  tableMaxRows: 26,
  tableMaxCols: 8,
  maxChars: 7000,
});
console.log("[QA] model explanation", explanationCheck.ndjson);
const reviewCheck = await workbook.inspect({
  kind: "table",
  range: `人工複核!A1:L${Math.min(5 + focusSize, 12)}`,
  include: "values,formulas",
  tableMaxRows: 12,
  tableMaxCols: 12,
  maxChars: 7000,
});
console.log("[QA] manual review", reviewCheck.ndjson);
const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
  summary: "final formula error scan",
  maxChars: 5000,
});
console.log("[QA] errors", errors.ndjson);

const qaDir = path.join(root, "qa", meta.as_of);
await fs.mkdir(qaDir, { recursive: true });
const renderSpecs = [
  ["儀表板", "A1:Q36", "dashboard.png"],
  ["模型說明", "A1:H26", "model_explanation.png"],
  ["量化排名", `A1:V${Math.min(lastDataRow, 16)}`, "ranking_left.png"],
  ["量化排名", `W1:AS${Math.min(lastDataRow, 16)}`, "ranking_right.png"],
  ["人工複核", `A1:L${Math.max(12, 5 + focusSize)}`, "manual_review.png"],
  ["參數", "A1:E47", "assumptions.png"],
  ["檢核", `A1:G${5 + checks.length}`, "checks.png"],
  ["資料來源", "A1:F13", "sources.png"],
];
for (const [sheetName, range, fileName] of renderSpecs) {
  const preview = await workbook.render({ sheetName, range, scale: 1, format: "png" });
  await fs.writeFile(path.join(qaDir, fileName), new Uint8Array(await preview.arrayBuffer()));
}

await fs.mkdir(path.dirname(outputPath), { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(`[完成] Excel: ${outputPath}`);
