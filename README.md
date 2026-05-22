# 🛡️ A股综合排雷工具

双维分析框架：**财报造假检测** + **ST退市风险筛查**，助你提前识别A股风险。

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![A股](https://img.shields.io/badge/适用-A股-orange.svg)
![Coze](https://img.shields.io/badge/平台-扣子(Coze)-blue.svg)

---

## 📌 功能特性

- **双维分析**：一次排雷，同时输出造假风险和ST退市风险两个维度
- **30条造假检测规则**：基于唐朝《手把手教你读财报》，7层系统化检查
- **7大类ST风险筛查**：基于2024年上市规则，覆盖财务/审计/规范/分红/交易/监管/造假
- **全自动数据获取**：EastMoney公开API，无需Token即可使用
- **年报PDF深度分析**：自动下载年报PDF，提取附注信息补充检测
- **同行对比**：自动获取同行数据，横向比较定位异常

---

## 🎯 双维评分体系

### 维度一：财报造假风险（Score A）

基于唐朝《手把手教你读财报》30条规则，逐项检测：

| 层级 | 检测内容 | 规则数 |
|------|---------|:-----:|
| Layer 0 | 门槛检查（审计意见、披露时效） | 2 |
| Layer 1 | 利润表信号（毛利率、减值等） | 6 |
| Layer 2 | 现金流量表信号（CF背离、持续为负等） | 3 |
| Layer 3 | 资产负债表信号（应收、存货、在建工程等） | 5 |
| Layer 4 | 交叉验证（CF/净利润、收现比等） | 5 |
| Layer 5 | 非财务信号（审计更换、减持、监管处罚等） | 9 |
| Layer 6 | 行业特有风险（农林牧渔、研发资本化） | 2 |

每条规则输出 PASS/WARN/FAIL/SKIP，加权评分：

| 得分 | 风险等级 |
|:----:|---------|
| 0-10 | 🟢 低风险 |
| 11-25 | 🟡 中风险 |
| 26-45 | 🟠 高风险 |
| 46+ | 🔴 极高风险 |

### 维度二：ST退市风险（Score B）

基于2024年沪深交易所上市规则，7大类风险筛查：

| 类别 | 风险项示例 | 最高分 |
|------|-----------|:-----:|
| 财务类 | 连续亏损、净资产为负、营收不达标 | +4 |
| 审计内控类 | 非标审计、内控否定、会计差错 | +3 |
| 规范类 | 资金占用、违规担保、账户冻结 | +4 |
| 分红类 | 分红不达标 | +2 |
| 交易类 | 股价<2元、市值<5亿 | +3 |
| 监管类 | 立案调查、处罚告知、造假认定 | +6 |
| 造假风险 | 造假嫌疑、造假确认 | +6 |

| 得分 | ST风险等级 |
|:----:|-----------|
| 0-2 | 🟢 ST低风险 |
| 3-4 | 🟡 ST中风险 |
| 5-7 | 🟠 ST高风险 |
| 8+ | 🔴 ST极高风险 |

### 综合评级

双维交叉判定，矩阵式输出：

| 造假风险(A) | ST风险(B) | 综合评级 |
|------------|-----------|---------|
| 低 | 低 | 🟢 低风险 |
| 中 | 低 | 🟡 中风险 |
| 高 | 低 | 🟠 高风险 |
| 极高/排除 | 任意 | 🔴 极高风险 |
| 任意 | 高/极高 | 🔴 极高风险 |

---

## 📊 验证结果

| 股票 | 代码 | 造假风险 | ST风险 | 综合 | 核心问题 |
|-----|:----:|:-------:|:-----:|:---:|---------|
| *ST元道 | 301139 | 84分🔴极高风险 | - | 🔴直接排除 | 虚增营收6.56亿，欺诈发行 |
| 江特电机 | 002176 | 高风险 | - | 🟠高风险 | 1.4亿资金拆借，主业亏损 |
| 合肥城建 | 002208 | 33分🟠高风险 | - | 🟠高风险 | 存货减值5.12亿，CF持续为负 |
| 顺控发展 | 003039 | 17分🟡中风险 | 0分🟢低风险 | 🟡中风险 | 跨行业并购，应收暴增 |
| 东风科技 | 600081 | 15分🟡中风险 | - | 🟡中风险 | 整体较干净，监事离任 |
| 贵州茅台 | 600519 | 低风险 | 0分🟢低风险 | 🟢低风险 | 优质龙头零误杀 |

---

## 🚀 安装与使用

### 方法一：扣子平台使用

1. 将 `skill/SKILL.md` 导入扣子技能
2. 输入股票代码 + "排雷"，如：`002176 排雷`

### 方法二：命令行使用

```bash
# 克隆仓库
git clone https://github.com/wangliangdong/financial-report-minesweeper.git
cd financial-report-minesweeper

# 安装依赖
pip install -r requirements.txt  # 或运行 install.sh

# 运行分析
python3 scripts/minesweeper_data.py --stock-code 002176 --years 10
```

### 可选：配置 Tushare Pro

```bash
cp .env.example .env
# 编辑 .env，填入 TUSHARE_TOKEN=your_token_here
```

> 不配置Tushare Token也可使用，默认走EastMoney公开API。

---

## 📁 项目结构

```
financial-report-minesweeper/
├── skill/
│   ├── SKILL.md                    # 扣子技能定义（核心文件）
│   ├── references/
│   │   └── checklist-rules.md      # 30条规则详细阈值
│   └── download-report.md          # 年报下载技能
├── scripts/
│   ├── minesweeper_data.py         # 数据获取主脚本
│   ├── eastmoney_data.py           # EastMoney API
│   ├── download_report.py          # 年报PDF下载
│   ├── tushare_collector.py        # Tushare数据采集
│   ├── config.py                   # 配置
│   ├── format_utils.py             # 格式化工具
│   └── tushare_modules/            # Tushare模块
├── 手把手读财报/                    # 唐朝方法论参考
├── install.sh                      # 安装脚本
├── .env.example                    # 环境变量模板
└── CHANGELOG.md                    # 更新日志
```

---

## 🔄 更新日志

### v2.0 - 双维分析框架
- ✨ 新增 Layer 7：ST退市风险筛查（2024年上市规则7大类）
- ✨ 双维评分体系：造假风险(Score A) + ST风险(Score B)
- ✨ 综合风险等级判定矩阵
- ✨ 报告输出增加"综合风险判定"段落
- 🔄 原stock_risk_check技能已合并，不再单独维护

### v1.1 - 初始版本
- 30条财报造假检测规则
- EastMoney + Tushare双数据源
- 年报PDF深度分析
- 同行对比

---

## 📧 联系作者

- GitHub: [@tulongshaoxia](https://github.com/tulongshaoxia)
- 欢迎提交Issue或Pull Request

---

**Made with ❤️ for A股投资者**

⚠️ 免责声明：本工具仅供参考，不构成投资建议。投资有风险，入市需谨慎。
