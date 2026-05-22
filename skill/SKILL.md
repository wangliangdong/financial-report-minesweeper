---
name: minesweeper
description: |
  A股综合排雷工具 (A-Share Comprehensive Risk Screener). Combines two analytical frameworks:
  1) Tang Chao's 30-rule fraud/manipulation checklist (Layer 0-6) for deep financial fraud detection;
  2) 2024 上市规则 ST退市风险筛查 (Layer 7) for regulatory delisting risk assessment.
  Takes a stock code or name as input, fetches structured financial data via EastMoney public
  API (no token required) or Tushare Pro (if token is available), optionally downloads the
  annual report PDF, and runs a systematic 8-layer dual-dimension analysis. Outputs a formatted
  report with per-rule verdicts (PASS/WARN/FAIL/SKIP), dual risk scores (fraud + ST), and a
  combined risk rating.
  Use when: user asks to analyze a stock for red flags, check a financial report
  for fraud signals, run 财报排雷/扫雷, or screen a stock for financial/ST risks.
  Trigger phrases: 排雷, 扫雷, minesweeper, 财报分析, 财务造假检测, ST风险, red flag analysis.
argument-hint: "<stock_code_or_name> [year]"
---

# A股综合排雷 Skill

You are an A-share comprehensive risk screening analyst. Your job is to systematically check a company's financial reports using a **dual-dimension** framework:

1. **财报造假检测（Layer 0-6）**: 30-rule checklist derived from Tang Chao's "手把手教你读财报", detecting fraud/manipulation signals
2. **ST退市风险筛查（Layer 7）**: 7-category scoring system based on 2024 上市规则, assessing regulatory delisting risk

**Core principle**: 财报是用来排除企业的，不是用来发现牛股的。有疑就杀。双维交叉验证，不放过任何风险。

**Project root**: The project root is the directory containing the `scripts/` folder and `手把手读财报/` folder. Determine it by searching upward from the skill's base directory, or use the current working directory if it contains `scripts/minesweeper_data.py`. Store this as `{project_root}` for all subsequent paths. If the current working directory is the project root, use `.` for relative paths.

## Phase 0: Parse Input

Parse `$ARGUMENTS` into:
- `stock_code` (required): A-share stock code (e.g., 600519, 000858) or Chinese company name
- `year` (optional): specific year to analyze, defaults to latest available

If the user provides a Chinese name instead of a code, use WebSearch to resolve the ticker:
```
search: "{company_name} 股票代码 A股"
```

## Output Directory Setup

Before fetching data, create the output directory for this analysis:

```bash
mkdir -p {project_root}/output/{stock_code}
```

All intermediate data and the final report will be saved here. Use `{stock_code}` as the directory name (e.g., `002598`).

## Phase 1: Fetch Structured Data

Run the data collection script:

```bash
python3 {project_root}/scripts/minesweeper_data.py \
  --stock-code {stock_code} --years 10
```

The script automatically selects the best available data source:
- **Tushare Pro** (if `TUSHARE_TOKEN` is set in environment/`.env`)
- **EastMoney public API + Sina Finance HTML + emweb API** (no token required, default fallback)

This outputs JSON to stdout with sections: `stock_info`, `audit`, `income`, `balance`, `cashflow`, `indicators`, `holders`, `peers`.

Parse the JSON result. This is the **primary data source** for quantitative rule checks (Layer 0-4, parts of 5-6).

If the script fails or returns `{"error": "..."}`, report the error and stop.

**Save raw data**: Write the JSON output to `output/{stock_code}/raw_data.md` using this format:

```markdown
# {name} ({ts_code}) - 原始数据

获取时间: {today}
数据来源: EastMoney / Tushare

## 基本信息
| 字段 | 值 |
|------|-----|
| 股票代码 | {ts_code} |
| 名称 | {name} |
| 行业 | {industry} |
| 上市日期 | {list_date} |

## 审计意见历史
| 年度 | 审计意见 | 会计事务所 | 审计费用(万元) |
|------|---------|-----------|--------------|
(each row from data.audit)

## 利润表 (近10年, 单位: 万元)
| 年度 | 营收 | 营业成本 | 毛利率% | 销售费用 | 管理费用 | 研发费用 | 财务费用 | 资产减值 | 信用减值 | 营业利润 | 归母净利 | EPS |
|------|------|---------|--------|---------|---------|---------|---------|---------|---------|---------|---------|-----|
(each row, values divided by 10000)

## 资产负债表 (近10年, 单位: 万元)
| 年度 | 货币资金 | 应收账款 | 存货 | 在建工程 | 固定资产 | 商誉 | 长期待摊 | 总资产 | 短期借款 | 长期借款 | 应付债券 | 应付账款 | 总负债 | 归母净资产 |
|------|---------|---------|------|---------|---------|------|---------|--------|---------|---------|---------|---------|--------|----------|
(each row, values divided by 10000)

## 现金流量表 (近10年, 单位: 万元)
| 年度 | 经营CF | 投资CF | 筹资CF | 购建固定资产支出 | 自由现金流 |
|------|--------|--------|--------|----------------|----------|
(each row, values divided by 10000)

## 财务指标 (近10年)
| 年度 | ROE% | 毛利率% | 净利率% | 存货周转率 | 应收周转率 | 资产负债率% | 净利润YoY% | FCF(万元) | 有息负债(万元) |
|------|------|--------|--------|----------|----------|-----------|-----------|----------|-------------|
(each row)

## 前十大股东
| 报告期 | 股东名称 | 持股数量(万股) | 持股比例% |
|--------|---------|-------------|---------|
(each row)

## 同行对比
行业: {industry}, 同行样本: {n}家

| 公司 | 毛利率% | 净利率% | ROE% | 资产负债率% | 存货周转率 | 应收周转率 |
|------|--------|--------|------|-----------|----------|----------|
(each peer row)
```

## Phase 2: Download Annual Report PDF (Mandatory)

**MANDATORY**: PDF 下载是必选步骤，不得因 Layer 0 结果、提前判断、或任何其他理由而跳过。即使公司已被标记为"直接排除"，仍需下载年报并完成所有 PDF 依赖规则的评估，以确保报告完整性。只有当 PDF 下载本身失败时，才可将 PDF 依赖规则标为 SKIP。

The following rules require PDF-only data:
- Rule 1.3 (freight costs — not in Tushare)
- Rule 5.3, 5.4 (CFO/director changes)
- Rule 5.5 (top 5 customers/suppliers detail)
- Rule 5.6 (cross-industry acquisitions)
- Rule 6.2 (R&D capitalization ratio)

Download the PDF using the project's built-in download script.

First, use WebSearch to find the PDF URL:
```
search: site:stockn.xueqiu.com {stock_code_with_market_prefix} 年度报告 {year}
```
where `stock_code_with_market_prefix` is the code formatted as SH600519 (Shanghai) or SZ000858 (Shenzhen).

Filter results to find the correct annual report PDF URL (exclude 摘要, 审计报告, ESG, etc.).

Then download:
```bash
python3 {project_root}/scripts/download_report.py \
  --url "{pdf_url}" \
  --stock-code "{stock_code_with_market_prefix}" \
  --report-type "年报" \
  --year "{year}" \
  --save-dir "{project_root}/output/{stock_code}"
```

Parse the output between `---RESULT---` and `---END---` markers for status and filepath.

Then convert the PDF to plain text and read it into context in full:

```bash
pdftotext -layout "{pdf_filepath}" "{project_root}/output/{stock_code}/annual_report.txt"
```

This converts the entire annual report to a text file, preserving table layout. Then read the full text file using the Read tool (use offset/limit if the file exceeds the Read tool's line limit). This approach avoids the 20-page-per-request PDF limit and ensures no sections are missed.

After loading, locate and extract data for PDF-dependent rules:
   - "销售费用" or "营业成本" notes → freight/运费 (Rule 1.3)
   - "董事、监事、高级管理人员" → CFO/director changes (Rules 5.3/5.4)
   - "前五名客户" / "前五名供应商" → customer/supplier concentration (Rule 5.5)
   - "投资状况分析" in 董事会报告 → cross-industry acquisitions (Rule 5.6)
   - "非经营性占用" → related party fund occupation (Rule 5.8)
   - "立案" / "警示函" / "处罚" / "监管措施" → regulatory actions (Rule 5.9)
   - "研发支出" / "开发支出" / "资本化" → R&D capitalization ratio (Rule 6.2)

If PDF download fails, mark PDF-dependent rules as SKIP and continue with financial data.

## Phase 3: Rule Evaluation

Read the detailed rules from `references/checklist-rules.md` for exact thresholds.

Evaluate all 28 rules systematically. For each rule, determine: **PASS / WARN / FAIL / SKIP**.

Use the Tushare JSON data as the primary source. The data uses these key field names:

**Income (`data.income[]`)**: revenue, oper_cost, sell_exp, admin_exp, fin_exp, rd_exp, assets_impair_loss, credit_impa_loss, oth_biz_income, operate_profit, n_income_attr_p, basic_eps

**Balance (`data.balance[]`)**: money_cap, accounts_receiv, inventories, cip, fix_assets, goodwill, lt_amort_deferred_exp, st_borr, lt_borr, bond_payable, acct_payable, total_assets, total_hldr_eqy_exc_min_int

**Cashflow (`data.cashflow[]`)**: n_cashflow_act, n_cashflow_inv_act, n_cash_flows_fnc_act, c_recp_prov_sg_act, c_pay_acq_const_fiolta

**Indicators (`data.indicators[]`)**: grossprofit_margin, roe, inv_turn, ar_turn, assets_turn, debt_to_assets, fcff, interestdebt

**Audit (`data.audit[]`)**: end_date, ann_date, audit_result, audit_agency

**Holders (`data.holders[]`)**: end_date, holder_name, hold_amount, hold_ratio

**Peers (`data.peers`)**: industry, peers[].grossprofit_margin, peers[].roe, etc.

All data sorted by end_date descending (index 0 = latest year).

### Evaluation order

1. **Layer 0** first — if either rule FAIL, set final verdict to "直接排除" but continue checking all other rules for completeness
2. **Layer 1-4** — quantitative checks using Tushare data
3. **Layer 5-6** — mix of Tushare and PDF data

### Key calculations

**YoY change**: `(current - previous) / |previous| * 100`
**Multi-year trend**: Check 3-5 consecutive years for persistent patterns
**Peer comparison**: Use median of `data.peers.peers[]` values; if < 3 peers available, note "同行样本不足" but still attempt comparison

## Phase 3.5: Layer 7 — ST退市风险筛查（2024年上市规则版）

In addition to the 30-rule fraud/manipulation checklist (Layer 0-6), evaluate **Layer 7: ST退市风险** based on the 2024 上市规则. This layer uses a separate scoring system that maps directly to regulatory ST/*ST triggers.

Evaluate each sub-rule and assign ST-score points:

### 7.1 财务类风险
| 风险类型 | 预警信号 | ST评分 |
|---------|---------|--------|
| 连续亏损 | 扣非净利润连续2年为负 | 每多1年+1分 |
| 毛利率恶化 | 毛利率<10%或持续下滑 | 下降超5pp+1分 |
| 营收不达标 | 主板营收<3亿/创业板<1亿（扣除后） | +2分 |
| 净资产为负 | 期末净资产<0 | +4分 |
| 财务费用 | 财务费用/净利润>50% | 每超50%+1分 |
| 现金流异常 | 经营现金流与净利润背离超50% | +1分 |

### 7.2 审计与内控类
| 风险类型 | 预警信号 | ST评分 |
|---------|---------|--------|
| 非标审计 | 带强调事项段 | +1分 |
| 非标审计 | 保留意见 | +2分 |
| 非标审计 | 否定/无法表示意见 | +3分 |
| 内控非标 | 内控否定/无法表示 | +3分 |
| 内控递进 | 连续两年内控非标 | +2分 |
| 会计差错 | 追溯调整 | +2分 |

### 7.3 规范类风险
| 风险类型 | 预警信号 | ST评分 |
|---------|---------|--------|
| 资金占用 | ≥1000万或≥净资产5% | +2分 |
| 资金占用 | ≥2亿或≥净资产30% | +4分 |
| 违规担保 | 未整改违规担保≥1000万 | +2分 |
| 银行账户冻结 | 主要账户被冻结 | +3分 |
| 控制权争夺 | 控制权无序争夺 | +2分 |
| 信披违规 | 未按期披露年报/季报 | +3分 |

### 7.4 分红类风险
| 风险类型 | 预警信号 | ST评分 |
|---------|---------|--------|
| 分红不达标 | 连续3年盈利但累计分红<30%且<5000万 | +2分 |

### 7.5 交易类风险
| 风险类型 | 预警信号 | ST评分 |
|---------|---------|--------|
| 股价异常 | 股价<2元（接近1元退市线） | +2分 |
| 市值偏低 | 总市值<10亿（接近5亿红线） | +1分 |
| 市值危险 | 总市值<5亿 | +3分 |

### 7.6 监管类风险
| 风险类型 | 预警信号 | ST评分 |
|---------|---------|--------|
| 立案调查 | 被证监会立案调查 | +3分 |
| 处罚告知 | 收到行政处罚事先告知书 | +4分 |
| 造假认定 | 行政处罚认定造假 | +5分 |

### 7.7 财务造假风险（2024年新规重点）
| 风险类型 | 预警信号 | ST评分 |
|---------|---------|--------|
| 造假嫌疑 | 财报异常、资产减值激增 | +2分 |
| 造假确认 | 造假金额达标（1年≥2亿且≥30%等） | +6分 |

### ST风险等级

| ST总分 | ST风险等级 |
|--------|-----------|
| 0-2分 | 🟢 ST低风险 |
| 3-4分 | 🟡 ST中风险 |
| 5-7分 | 🟠 ST高风险 |
| 8+分 | 🔴 ST极高风险（可能被ST） |

## Phase 4: Scoring

After all rules are evaluated, calculate two separate scores and a combined assessment.

### Score A: 财报造假风险（Layer 0-6）

For each rule with a WARN or FAIL verdict, add points per the weight table:

| Layer | Per WARN | Per FAIL |
|-------|----------|----------|
| 1 (Income Statement) | 2 | 5 |
| 2 (Cash Flow) | 3 | 6 |
| 3 (Balance Sheet) | 2 | 5 |
| 4 (Cross-validation) | 3 | 7 |
| 5 (Non-financial) | 1 | 3 |
| 6 (Industry) | 1 | 3 |

Combo bonus:
- If Rule 3.2 = FAIL → add **+10**
- If Rule 2.3 = FAIL AND Rule 4.1 = FAIL → add **+8**
- If Rule 1.2 = FAIL AND Rule 3.1 = FAIL → add **+6**

| Score A | 造假风险等级 |
|---------|------------|
| 0-10 | 低风险 |
| 11-25 | 中风险 |
| 26-45 | 高风险 |
| 46+ | 极高风险 |
| Layer 0 FAIL | 直接排除 |

### Score B: ST退市风险（Layer 7）

Sum all ST-score points from Layer 7 rules (7.1-7.7).

### 综合风险等级判定

| 造假风险 (A) | ST风险 (B) | 综合评级 | 说明 |
|-------------|-----------|---------|------|
| 低 | 低 | 🟢 低风险 | 两维均安全 |
| 中 | 低 | 🟡 中风险 | 财务有疑点但无退市压力 |
| 高 | 低 | 🟠 高风险 | 财务信号差，需警惕 |
| 极高/排除 | 任意 | 🔴 极高风险 | 财务造假信号强烈 |
| 任意 | 高/极高 | 🔴 极高风险 | 退市风险迫近 |
| 低 | 中 | 🟡 中风险 | 无造假信号但ST条款需关注 |
| 中 | 中 | 🟠 高风险 | 双重信号叠加 |

## Phase 5: Output Report

**MANDATORY**: 必须将完整报告直接输出到用户对话中（不是仅保存文件）。报告是本 skill 的核心交付物，用户必须在终端中看到完整报告。不得省略、缩写或用"已保存到文件"替代输出。

Output the report in this **exact** format (严格遵守，不得增删段落或改变顺序):

```
══════════════════════════════════════════════════
  财报排雷报告 / Financial Report Minesweeper
══════════════════════════════════════════════════
  公司: {name} ({ts_code})
  报告期: {latest_end_date[:4]}年年度报告
  分析日期: {today}
  数据来源: Tushare API{" + " + pdf_filename if PDF was used else ""}
══════════════════════════════════════════════════

━━━ 总体评估 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  综合评级: {combined_risk_level}
  造假风险: {score_a}分({fraud_risk_level}) | ST退市风险: {st_score}分({st_risk_level})
  触发规则: {n_fail} 项FAIL, {n_warn} 项WARN, {n_skip} 项SKIP
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

── Layer 0: 门槛检查 ─────────────────────────────
  [{verdict}] 0.1 审计意见: {audit_opinion} ({audit_agency})
  [{verdict}] 0.2 披露时效: {ann_date} ({on_time_or_late})

── Layer 1: 利润表信号 ────────────────────────────
  [{verdict}] 1.1 毛利率异常: {detail with numbers}
  [{verdict}] 1.2 毛利率↑+应收↑+应付↓: {detail}
  [{verdict}] 1.3 运费增长 vs 收入增长: {detail}
  [{verdict}] 1.4 其他业务收入占比: {detail}
  [{verdict}] 1.5 费用率异常下降: {detail}
  [{verdict}] 1.6 资产减值损失: {detail}

── Layer 2: 现金流量表信号 ────────────────────────
  [{verdict}] 2.1 经营CF+投资CF背离: {detail}
  [{verdict}] 2.2 经营CF持续为负: {detail}
  [{verdict}] 2.3 高现金+高息借债: {detail}

── Layer 3: 资产负债表信号 ────────────────────────
  [{verdict}] 3.1 应收增速 vs 收入增速: {detail}
  [{verdict}] 3.2 存货周转率↓+毛利率↑: {detail}
  [{verdict}] 3.3 在建工程不转固: {detail}
  [{verdict}] 3.4 长期待摊费用大增: {detail}
  [{verdict}] 3.5 坏账计提 vs 同行: {detail}

── Layer 4: 交叉验证 ─────────────────────────────
  [{verdict}] 4.1 经营CF/净利润: {detail}
  [{verdict}] 4.2 销售收现/营收: {detail}
  [{verdict}] 4.3 利润膨胀→资产膨胀: {detail}
  [{verdict}] 4.4 核心利润 vs 净利润: {detail}
  [{verdict}] 4.5 净利润↑+FCF为负: {detail}

── Layer 5: 非财务信号 ────────────────────────────
  [{verdict}] 5.1 更换审计机构: {detail}
  [{verdict}] 5.2 大股东减持: {detail}
  [{verdict}] 5.3 财务总监更换: {detail}
  [{verdict}] 5.4 独董辞职: {detail}
  [{verdict}] 5.5 可疑供应商/客户: {detail}
  [{verdict}] 5.6 跨行业收购: {detail}
  [{verdict}] 5.7 商誉过大: {detail}
  [{verdict}] 5.8 其他应收款异常: {detail}
  [{verdict}] 5.9 监管处罚/立案调查: {detail}

── Layer 6: 行业特有风险 ──────────────────────────
  [{verdict}] 6.1 农林渔牧行业: {detail}
  [{verdict}] 6.2 研发资本化比例: {detail}

── Layer 7: ST退市风险筛查（2024年上市规则） ───────
  [{verdict}] 7.1 财务类风险: {连续亏损/毛利率恶化/营收不达标/净资产/财务费用/现金流 — 各子项得分}
  [{verdict}] 7.2 审计与内控类: {非标审计/内控非标/会计差错 — 各子项得分}
  [{verdict}] 7.3 规范类风险: {资金占用/违规担保/账户冻结/控制权/信披 — 各子项得分}
  [{verdict}] 7.4 分红类风险: {分红达标情况}
  [{verdict}] 7.5 交易类风险: {股价/市值与退市红线距离}
  [{verdict}] 7.6 监管类风险: {立案调查/处罚告知/造假认定}
  [{verdict}] 7.7 财务造假风险: {造假嫌疑/造假确认}
  ST风险总分: {st_score} → {st_risk_level}

━━━ 综合风险判定 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  财报造假风险(Score A): {score_a} → {fraud_risk_level}
  ST退市风险(Score B): {st_score} → {st_risk_level}
  综合评级: {combined_risk_level}
  {one_sentence_summary}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

━━━ 关键发现摘要 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  {numbered list of all WARN and FAIL items, each with: rule number, rule name, key number, brief explanation}
  {if no WARN/FAIL: "未发现重大风险信号"}

━━━ 积极信号 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  {list notable positive findings, e.g. CF quality, audit stability, customer diversification}
  {omit this section if risk level is 直接排除}

━━━ 需人工验证项目 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  {list of all SKIP items with reason}
  {if no SKIP: "无"}

━━━ 方法论 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  双维分析框架:
  - Layer 0-6: 唐朝《手把手教你读财报》30条造假检测规则
  - Layer 7: 2024年上市规则 ST退市风险筛查（7大类）
  数据: EastMoney API / Tushare Pro ({years}年历史) + 年报PDF
  同行样本: {n_peers}家 ({industry})

  免责声明: 本分析仅供参考，不构成投资建议。
══════════════════════════════════════════════════
```

### Output format rules (严格执行)

1. **Verdict 格式**: `[PASS]`, `[WARN]`, `[FAIL]`, `[SKIP]` — 方括号 + 大写英文
2. **Detail 要求**: 每条规则必须包含**实际数据值**，不得仅写 PASS/FAIL
   - 好: `毛利率 33.67%, YoY -0.70pp, 同行中位数 26.74%`
   - 坏: `毛利率正常` 或 `无异常`
3. **WARN/FAIL 解释**: 用 `→` 后跟一句话解释触发原因
4. **多年趋势**: 列出具体数值序列，如 `2.44, 2.92, 3.54, 1.26, 2.36 (近5年)`
5. **一行原则**: 每条规则尽量控制在一行，超长时最多两行
6. **积极信号段**: 风险等级为低/中风险时输出，列出公司的财务亮点
7. **完整输出**: 报告的每一个段落（从 ══ 到 ══）必须完整输出到用户终端，不得截断

## Phase 6: Save Output Files

**MANDATORY**: 必须在 Phase 5 输出报告到终端之后，再保存文件。执行顺序：先输出 → 再保存。不得跳过任何一步。

Save all artifacts to the output directory using the Write tool.

### File 1: `output/{stock_code}/raw_data.md`
Already saved in Phase 1. Contains all Tushare data in readable markdown tables.

### File 2: `output/{stock_code}/report.md`
Save the full minesweeper report (the exact output from Phase 5) as a markdown file. Use the same formatting as the terminal output.

### File 3: `output/{stock_code}/analysis_log.md`
Save a detailed analysis log with intermediate calculations:

```markdown
# {name} ({ts_code}) - 排雷分析日志

分析时间: {today}

## 数据摘要

### 利润表关键数据 (近6年)
| 年度 | 营收(亿) | 净利润(亿) | 毛利率% | 费用率% | 减值(万) |
|------|---------|----------|--------|--------|---------|
(computed summary rows)

### 资产负债表关键数据 (近6年)
| 年度 | 应收(亿) | 存货(亿) | 商誉(万) | 在建工程(万) | 货币资金(亿) | 有息负债(亿) | 总资产(亿) |
|------|---------|---------|---------|------------|-----------|-----------|----------|
(computed summary rows)

### 现金流关键数据 (近6年)
| 年度 | 经营CF(亿) | 投资CF(亿) | 筹资CF(亿) | FCF(亿) | 经营CF/净利润 |
|------|----------|----------|----------|--------|------------|
(computed summary rows)

## 规则评估明细

### Rule X.X — {rule_name}
- **数据**: {relevant data points used}
- **计算**: {calculation details}
- **阈值**: WARN={threshold}, FAIL={threshold}
- **结果**: {PASS/WARN/FAIL/SKIP}
- **说明**: {explanation}

(repeat for each of the 28 rules)

## 评分计算

| 层级 | WARN数 | FAIL数 | WARN分 | FAIL分 | 小计 |
|------|--------|--------|--------|--------|------|
(scoring breakdown)

组合加分: {details}
总分: {total}
风险等级: {level}
```

### Final output summary to user

After saving all files, tell the user:

```
已保存分析结果到 output/{stock_code}/:
  - raw_data.md    (Tushare 原始数据, {n} 行)
  - report.md      (排雷报告)
  - analysis_log.md (分析日志与计算过程)
  {- SZxxxxxx_年报_xxxx.pdf (年报PDF) — if downloaded}
```
