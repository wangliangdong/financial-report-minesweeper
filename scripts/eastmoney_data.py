#!/usr/bin/env python3
"""EastMoney (东方财富) 公开数据获取模块

使用东方财富 datacenter API + emweb 页面 + 新浪财经 HTML 解析
获取 A 股财报数据，无需任何 Token。

主要数据源:
- 东方财富 datacenter API:
  - RPT_DMSK_FN_INCOME (利润表)
  - RPT_DMSK_FN_BALANCE (资产负债表)
  - RPT_DMSK_FN_CASHFLOW (现金流量表)
  - RPT_F10_BASIC_ORGINFO (基本信息)
  - RPT_F10_FINANCE_MAINFINADATA (综合财务指标)
- 东方财富 emweb API:
  - 十大股东 (PC_HSF10/ShareholderResearch/PageAjax)
- 新浪财经 HTML:
  - 利润表/资产负债表/现金流量表 (补充缺失字段)
- 巨潮资讯 API (审计意见备用)

API 文档参考:
https://datacenter-web.eastmoney.com/api/data/v1/get
"""

from __future__ import annotations

import functools
import json
import math
import re
import sys
import time
from io import StringIO
from typing import Any, Optional

import pandas as pd
import requests

# ─────────────────────────────────────────────────────────────
# 全局配置
# ─────────────────────────────────────────────────────────────
_BASE_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
_EMWEB_URL = "https://emweb.securities.eastmoney.com/PC_HSF10/ShareholderResearch/PageAjax"
_SINA_INCOME_URL = "https://money.finance.sina.com.cn/corp/go.php/vFD_ProfitStatement/stockid/{code}/ctrl/part/displaytype/4.phtml"
_SINA_BALANCE_URL = "https://money.finance.sina.com.cn/corp/go.php/vFD_BalanceSheet/stockid/{code}/ctrl/part/displaytype/4.phtml"
_SINA_CASHFLOW_URL = "https://money.finance.sina.com.cn/corp/go.php/vFD_CashFlow/stockid/{code}/ctrl/part/displaytype/4.phtml"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://data.eastmoney.com/",
    "Accept": "application/json",
}
_SINA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://finance.sina.com.cn/",
}
_TIMEOUT = 30
_MAX_RETRIES = 3
_RETRY_DELAY = 2.0  # seconds

# 简单内存缓存 TTL=10分钟
_CACHE: dict[str, tuple[float, Any]] = {}


def _rate_limit(func):
    """装饰器：强制两次请求间隔 >= 0.3s，避免被限流"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        time.sleep(0.3)
        return func(*args, **kwargs)
    return wrapper


def _get_cache(key: str) -> Optional[Any]:
    now = time.time()
    if key in _CACHE:
        ts, val = _CACHE[key]
        if now - ts < 600:
            return val
        del _CACHE[key]
    return None


def _set_cache(key: str, val: Any) -> None:
    _CACHE[key] = (time.time(), val)


# ─────────────────────────────────────────────────────────────
# 核心 HTTP 请求
# ─────────────────────────────────────────────────────────────
@_rate_limit
def _em_request(
    params: dict[str, Any],
    cache_key: Optional[str] = None,
) -> dict | None:
    """向东方财富 API 发请求，带缓存+重试+超时。"""
    if cache_key:
        cached = _get_cache(cache_key)
        if cached is not None:
            return cached

    for attempt in range(_MAX_RETRIES):
        try:
            resp = requests.get(
                _BASE_URL,
                params=params,
                headers=_HEADERS,
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("success") and data.get("result"):
                result = data["result"]
                if cache_key:
                    _set_cache(cache_key, result)
                return result

            # 接口返回 success=false 或 result=null 也视为空
            if attempt < _MAX_RETRIES - 1:
                time.sleep(_RETRY_DELAY)
                continue
            return None

        except (requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
                requests.exceptions.HTTPError) as e:
            if attempt < _MAX_RETRIES - 1:
                time.sleep(_RETRY_DELAY * (attempt + 1))
            else:
                print(f"Warning: EastMoney API failed after {_MAX_RETRIES} attempts: {e}",
                      file=sys.stderr)
                return None
        except Exception as e:
            print(f"Warning: EastMoney API unexpected error: {e}", file=sys.stderr)
            return None

    return None


@_rate_limit
def _emweb_request(url: str, params: dict[str, Any],
                    cache_key: Optional[str] = None) -> dict | None:
    """向东方财富 emweb API 发请求，带缓存+重试+超时。"""
    if cache_key:
        cached = _get_cache(cache_key)
        if cached is not None:
            return cached

    for attempt in range(_MAX_RETRIES):
        try:
            resp = requests.get(
                url,
                params=params,
                headers=_HEADERS,
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            if cache_key:
                _set_cache(cache_key, data)
            return data

        except Exception as e:
            if attempt < _MAX_RETRIES - 1:
                time.sleep(_RETRY_DELAY * (attempt + 1))
                continue
            print(f"Warning: EastMoney emweb failed: {e}", file=sys.stderr)
            return None
    return None


def _sina_request(url: str, cache_key: Optional[str] = None) -> str | None:
    """请求新浪财经页面，返回 HTML 文本。"""
    if cache_key:
        cached = _get_cache(cache_key)
        if cached is not None:
            return cached

    for attempt in range(_MAX_RETRIES):
        try:
            resp = requests.get(
                url,
                headers=_SINA_HEADERS,
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            # 新浪使用 GB2312/GBK 编码
            resp.encoding = "gb2312"
            text = resp.text
            if cache_key:
                _set_cache(cache_key, text)
            return text
        except Exception as e:
            if attempt < _MAX_RETRIES - 1:
                time.sleep(_RETRY_DELAY * (attempt + 1))
                continue
            print(f"Warning: Sina Finance request failed: {e}", file=sys.stderr)
            return None
    return None


# ─────────────────────────────────────────────────────────────
# 代码格式转换
# ─────────────────────────────────────────────────────────────
def ts_code_to_em_code(ts_code: str) -> str:
    """将 Tushare 格式代码转为东方财富纯数字代码 (无后缀)。"""
    code = ts_code.split(".")[0]
    return code.zfill(6)


def em_code_to_ts_code(em_code: str) -> str:
    """将东方财富纯数字代码转为 Tushare 格式。"""
    code = em_code.zfill(6)
    if code.startswith("6"):
        return f"{code}.SH"
    else:
        return f"{code}.SZ"


def em_code_to_sina_code(em_code: str) -> str:
    """将东方财富纯数字代码转为新浪格式。"""
    return em_code.zfill(6)


def _normalize_date(raw: Any) -> Optional[str]:
    """将 '2025-12-31 00:00:00' 或 '20251231' 格式转为 'YYYYMMDD'。"""
    if not raw:
        return None
    s = str(raw).strip()
    # 已经是 YYYYMMDD 纯数字
    if re.match(r"^\d{8}$", s):
        return s
    # ISO-like: 2025-12-31 00:00:00
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return m.group(1) + m.group(2) + m.group(3)
    return None


# ─────────────────────────────────────────────────────────────
# 通用数据提取辅助
# ─────────────────────────────────────────────────────────────
def _safe_num(v: Any) -> Optional[float]:
    """将任意值转为 float 或 None。"""
    if v is None or v == "" or v == "--":
        return None
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (ValueError, TypeError):
        return None


def _to_wan(v: Any) -> Optional[float]:
    """将元转为万元（除以 10000），东方财富数据默认单位为元。"""
    f = _safe_num(v)
    if f is None:
        return None
    return f / 10000.0


def _safe_str(v: Any) -> str:
    if v is None or v == "" or v == "--":
        return ""
    return str(v)


def _rows_to_list(result: dict | None, ts_code: str,
                   date_col: str = "REPORT_DATE") -> list[dict]:
    """将 EastMoney API result 转为 [{ts_code, end_date, ...}, ...] 列表。"""
    if not result or not result.get("data"):
        return []
    rows = result["data"]
    if not isinstance(rows, list):
        rows = [rows]

    out = []
    for row in rows:
        end_date = _normalize_date(row.get(date_col))
        if not end_date:
            continue
        # 只保留年报 (YYYY-12-31)
        if not end_date.endswith("1231"):
            continue
        item = {"ts_code": ts_code, "end_date": end_date}
        # 把原始字段全部带出（映射时按需取用）
        item["_raw"] = row
        out.append(item)
    return out


# ─────────────────────────────────────────────────────────────
# 新浪财经 HTML 解析
# ─────────────────────────────────────────────────────────────
# 新浪中文科目名 → Tushare 字段名 映射
_SINA_INCOME_MAP = {
    "营业收入": "revenue",
    "营业成本": "oper_cost",
    "销售费用": "sell_exp",
    "管理费用": "admin_exp",
    "研发费用": "rd_exp",
    "财务费用": "fin_exp",
    "资产减值损失": "assets_impair_loss",
    "信用减值损失": "credit_impa_loss",
    "其他业务收入": "oth_biz_income",
    "其他业务成本": "oth_biz_cost",
    "营业利润": "operate_profit",
    "利润总额": "total_profit",
    "归属于母公司所有者的净利润": "n_income_attr_p",
    "基本每股收益": "basic_eps",
    "净利润": "n_income",
    "所得税": "income_tax",
    "营业税金及附加": "biz_tax_surchg",
}

_SINA_BALANCE_MAP = {
    "货币资金": "money_cap",
    "应收账款": "accounts_receiv",
    "存货": "inventories",
    "在建工程": "cip",
    "固定资产": "fix_assets",
    "商誉": "goodwill",
    "长期待摊费用": "lt_amort_deferred_exp",
    "短期借款": "st_borr",
    "长期借款": "lt_borr",
    "应付债券": "bond_payable",
    "应付账款": "acct_payable",
    "其他应收款": "oth_receiv",
    "总资产": "total_assets",
    "总负债": "total_liab",
    "归属母公司股东权益": "total_hldr_eqy_exc_min_int",
    "无形资产": "intang_assets",
    "应收票据": "notes_receiv",
    "预付款项": "prepayment",
    "其他应收款": "oth_receiv",
    "流动资产合计": "total_cur_assets",
    "长期股权投资": "lt_eqt_invest",
    "非流动资产合计": "total_nca",
    "应付票据": "notes_payable",
    "预收款项": "adv_receipts",
    "流动负债合计": "total_cur_liab",
    "长期应付款": "total_ncl",
    "递延所得税负债": "defer_tax_liab",
    "递延所得税资产": "defer_tax_assets",
    "少数股东权益": "minority_int",
    "股东权益合计": "total_hldr_eqy",
    "一年内到期的非流动负债": "non_cur_liab_due_1y",
}

_SINA_CASHFLOW_MAP = {
    "销售商品、提供劳务收到的现金": "c_recp_prov_sg_act",
    "经营活动现金流量净额": "n_cashflow_act",
    "投资活动现金流量净额": "n_cashflow_inv_act",
    "筹资活动现金流量净额": "n_cash_flows_fnc_act",
    "购建固定资产、无形资产和其他长期资产支付的现金": "c_pay_acq_const_fiolta",
    "处置固定资产、无形资产和其他长期资产收回的现金净额": "n_recp_disp_fiolta",
    "期末现金及现金等价物余额": "n_cash_end_bal",
    "期初现金及现金等价物余额": "n_cash_beg_bal",
}


def _parse_sina_table(html: str, name_map: dict[str, str]) -> dict[str, dict[str, float]]:
    """解析新浪财经 HTML 表格，返回 {date: {field: value}}。
    
    新浪表格结构：列名是第一行（日期），后面是科目名+数值。
    单位：万元（新浪显示"单位：万元"，数值已经是万元）
    """
    try:
        tables = pd.read_html(StringIO(html), flavor='html5lib')
    except Exception as e:
        print(f"Warning: Failed to parse Sina HTML tables: {e}", file=sys.stderr)
        return {}

    if not tables:
        return {}

    # 找最大的表（通常是主数据表）
    best_table = None
    best_score = 0
    for i, tbl in enumerate(tables):
        if tbl.shape[0] > 5 and tbl.shape[1] > 3:
            score = tbl.shape[0] * tbl.shape[1]
            if score > best_score:
                best_score = score
                best_table = tbl

    if best_table is None:
        return {}

    # 处理表格：清洗数据
    try:
        df = best_table.copy()
        
        # 第一列应该是科目名，其余列是各期数据
        # 先清理列名：去掉 NaN 或无效列
        df = df.dropna(how='all')
        
        # 第一列是科目名，后面是日期数据
        # 设置第一列为索引（科目名）
        df = df.set_index(df.columns[0])
        df.index = df.index.fillna("")
        
        # 转换数值列
        for col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # 过滤年份列：只保留 12-31 结尾的列（年报）
        year_cols = [c for c in df.columns if str(c).endswith("12-31") or 
                     (isinstance(c, str) and re.match(r'\d{4}-\d{2}-\d{2}', str(c)))]
        if not year_cols:
            # 尝试用第一行作为列名
            year_cols = [c for c in df.columns]
        
        df = df[year_cols]
        
        # 构建 {date: {field: value}}
        result = {}
        for date_col in year_cols:
            # 标准化日期
            date_str = str(date_col)
            m = re.match(r'(\d{4})-(\d{2})-(\d{2})', date_str)
            if m:
                date_str = m.group(1) + m.group(2) + m.group(3)
            else:
                date_str = date_str.replace("-", "")
            
            if not date_str.endswith("1231"):
                continue
            
            row_data = {}
            for idx, val in df[date_col].items():
                idx_str = str(idx).strip()
                if not idx_str:
                    continue
                # 尝试映射
                for cn_name, ts_name in name_map.items():
                    if cn_name in idx_str or idx_str in cn_name:
                        row_data[ts_name] = _safe_num(val)
                        break
                else:
                    # 尝试直接匹配
                    for cn_name, ts_name in name_map.items():
                        if cn_name == idx_str:
                            row_data[ts_name] = _safe_num(val)
                            break
            
            if row_data:
                result[date_str] = row_data
        
        return result
        
    except Exception as e:
        print(f"Warning: Failed to process Sina table: {e}", file=sys.stderr)
        return {}


def _fetch_sina_income(em_code: str) -> dict[str, dict[str, float]]:
    """获取新浪利润表数据。"""
    sina_code = em_code_to_sina_code(em_code)
    url = _SINA_INCOME_URL.format(code=sina_code)
    html = _sina_request(url, cache_key=f"sina_income:{em_code}")
    if not html:
        return {}
    return _parse_sina_table(html, _SINA_INCOME_MAP)


def _fetch_sina_balance(em_code: str) -> dict[str, dict[str, float]]:
    """获取新浪资产负债表数据。"""
    sina_code = em_code_to_sina_code(em_code)
    url = _SINA_BALANCE_URL.format(code=sina_code)
    html = _sina_request(url, cache_key=f"sina_balance:{em_code}")
    if not html:
        return {}
    return _parse_sina_table(html, _SINA_BALANCE_MAP)


def _fetch_sina_cashflow(em_code: str) -> dict[str, dict[str, float]]:
    """获取新浪现金流量表数据。"""
    sina_code = em_code_to_sina_code(em_code)
    url = _SINA_CASHFLOW_URL.format(code=sina_code)
    html = _sina_request(url, cache_key=f"sina_cashflow:{em_code}")
    if not html:
        return {}
    return _parse_sina_table(html, _SINA_CASHFLOW_MAP)


def _merge_sina_data(
    em_list: list[dict],
    sina_data: dict[str, dict[str, float]],
    fields: list[str],
) -> list[dict]:
    """将新浪解析的数据合并到东方财富数据列表中。"""
    # 构建 {date: sina_row}
    for item in em_list:
        end_date = item.get("end_date", "")
        if end_date in sina_data:
            sina_row = sina_data[end_date]
            for field in fields:
                # 只在原值为空时用新浪数据补充
                if item.get(field) is None and sina_row.get(field) is not None:
                    item[field] = sina_row[field]
    return em_list


# ─────────────────────────────────────────────────────────────
# 1. 基本信息 (stock_info)
# ─────────────────────────────────────────────────────────────
def get_stock_info(em_code: str) -> dict:
    """获取股票基本信息。返回 Tushare 格式的 stock_info。"""
    params = {
        "reportName": "RPT_F10_BASIC_ORGINFO",
        "columns": (
            "SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,"
            "ORG_NAME,INDUSTRYCSRC1,EM2016,BOARD_NAME_LEVEL,"
            "TRADE_MARKET,PROVINCE,LISTING_DATE"
        ),
        "filter": f'(SECURITY_CODE="{em_code}")',
        "pageNumber": 1,
        "pageSize": 1,
        "source": "HSF10",
    }
    result = _em_request(params, cache_key=f"basic:{em_code}")
    if not result or not result.get("data"):
        return {
            "ts_code": em_code_to_ts_code(em_code),
            "name": "",
            "industry": "",
            "area": "",
            "market": "",
            "list_date": "",
            "fullname": "",
        }

    rows = result["data"]
    if isinstance(rows, list) and rows:
        row = rows[0]
    else:
        row = rows

    # 保存完整行业路径用于同行搜索，同时提取简化名称用于显示
    # EM2016 = "食品饮料-饮料-白酒"（东方财富分类）
    # 同行搜索需要精确匹配整个值；BOARD_NAME_LEVEL 包含更细分的小类
    em2016 = _safe_str(row.get("EM2016") or "")
    board_level = _safe_str(row.get("BOARD_NAME_LEVEL") or "")
    industrycsrc = _safe_str(row.get("INDUSTRYCSRC1") or "")

    # 简化行业名：取 EM2016 最后一段
    if em2016 and "-" in em2016:
        industry = em2016.split("-")[-1]
    elif board_level and "-" in board_level:
        industry = board_level.split("-")[-1]
    elif industrycsrc:
        industry = industrycsrc
    else:
        industry = ""

    # 保存完整行业路径用于同行对比（_peer_industry_raw）
    _peer_industry_raw = em2016 or board_level or ""

    return {
        "ts_code": _safe_str(row.get("SECUCODE")) or em_code_to_ts_code(em_code),
        "name": _safe_str(row.get("SECURITY_NAME_ABBR")),
        "industry": industry,
        "_peer_industry_raw": _peer_industry_raw,
        "area": _safe_str(row.get("PROVINCE")),
        "market": _safe_str(row.get("TRADE_MARKET")),
        "list_date": (_normalize_date(row.get("LISTING_DATE")) or "")[:8],
        "fullname": _safe_str(row.get("ORG_NAME")),
    }


# ─────────────────────────────────────────────────────────────
# 2. 利润表 (income) — 从 RPT_DMSK_FN_INCOME + 新浪补充
# ─────────────────────────────────────────────────────────────
def _map_income_row(raw: dict) -> dict:
    """将一行 EastMoney income 原始数据映射为 Tushare 字段。

    注意：东方财富数据单位为"元"，Tushare 通常用"万元"，需除以 10000。
    EPS（每股收益）单位为 元/股，不应转换。
    """
    # revenue
    revenue = _to_wan(raw.get("TOTAL_OPERATE_INCOME"))
    # oper_cost (EastMoney 的 OPERATE_COST = 营业成本)
    oper_cost = _to_wan(raw.get("OPERATE_COST"))
    # sell_exp
    sell_exp = _to_wan(raw.get("SALE_EXPENSE"))
    # admin_exp
    admin_exp = _to_wan(raw.get("MANAGE_EXPENSE"))
    # fin_exp
    fin_exp = _to_wan(raw.get("FINANCE_EXPENSE"))
    # rd_exp — EastMoney income 表不直接提供，设为 None（后续从新浪补）
    rd_exp = None

    # assets_impair_loss
    assets_impair_loss = _to_wan(raw.get("ASSET_IMPAIR_LOSS") or raw.get("IMPAIRMENT_LOSS_ON_ASSETS"))
    # credit_impa_loss
    credit_impa_loss = _to_wan(raw.get("CREDIT_IMPAIR_LOSS") or raw.get("IMPAIRMENT_LOSS_ON_CREDIT"))

    # oth_biz_income / oth_biz_cost
    oth_biz_income = _to_wan(raw.get("OTHER_BUSINESS_INCOME"))
    oth_biz_cost = _to_wan(raw.get("OTHER_BUSINESS_EXPENSE"))

    # operate_profit
    operate_profit = _to_wan(raw.get("OPERATE_PROFIT"))
    # total_profit
    total_profit = _to_wan(raw.get("TOTAL_PROFIT"))
    # income_tax
    income_tax = _to_wan(raw.get("INCOME_TAX"))
    # n_income (净利润)
    n_income = _to_wan(raw.get("PARENT_NETPROFIT"))  # 东方财富 income 里没有独立净利润
    # n_income_attr_p
    n_income_attr_p = _to_wan(raw.get("PARENT_NETPROFIT"))

    # 净利润 / 总股本 (REG_CAPITAL 万元 = 亿股)
    parent_netprofit = _safe_num(raw.get("PARENT_NETPROFIT"))
    total_shares = _safe_num(raw.get("TOTAL_SHARES")) or _safe_num(raw.get("REG_CAPITAL"))
    if parent_netprofit and total_shares and total_shares != 0:
        basic_eps = parent_netprofit / total_shares / 10000.0  # 万元/万元=元/股
        diluted_eps = basic_eps  # 东方财富通常不区分
    else:
        basic_eps = _safe_num(raw.get("BASIC_EPS"))
        diluted_eps = _safe_num(raw.get("DILUTED_EPS"))

    return {
        "revenue": revenue,
        "oper_cost": oper_cost,
        "sell_exp": sell_exp,
        "admin_exp": admin_exp,
        "rd_exp": rd_exp,
        "fin_exp": fin_exp,
        "assets_impair_loss": assets_impair_loss,
        "credit_impa_loss": credit_impa_loss,
        "oth_biz_income": oth_biz_income,
        "oth_biz_cost": oth_biz_cost,
        "operate_profit": operate_profit,
        "total_profit": total_profit,
        "income_tax": income_tax,
        "n_income": n_income,
        "n_income_attr_p": n_income_attr_p,
        "deduct_n_income": _to_wan(raw.get("DEDUCT_PARENT_NETPROFIT")),
        "basic_eps": basic_eps,
        "diluted_eps": diluted_eps,
        # 下面字段东方财富 income 表不直接提供
        "biz_tax_surchg": _to_wan(raw.get("OPERATE_TAX_ADD")),
        "invest_income": _to_wan(raw.get("INVEST_INCOME")),
        "asset_disp_income": None,
        "fv_value_chg_gain": None,
        "non_oper_income": None,
        "non_oper_exp": None,
    }


def get_income_data(em_code: str, years: int = 10) -> list[dict]:
    """获取利润表数据 (年报)，使用 ALL 列避免字段不存在错误。"""
    params = {
        "reportName": "RPT_DMSK_FN_INCOME",
        "columns": "ALL",
        "filter": f'(SECURITY_CODE="{em_code}")(DATE_TYPE_CODE="001")',
        "pageNumber": 1,
        "pageSize": years,
        "sortTypes": -1,
        "sortColumns": "REPORT_DATE",
        "source": "HSF10",
    }
    result = _em_request(params, cache_key=f"income:{em_code}")
    if not result or not result.get("data"):
        return []
    rows = result["data"]
    if not isinstance(rows, list):
        rows = [rows]
    out = []
    for row in rows:
        end_date = _normalize_date(row.get("REPORT_DATE"))
        if not end_date or not end_date.endswith("1231"):
            continue
        # Filter out ratio columns and metadata columns
        raw = {k: v for k, v in row.items()
               if not k.endswith("_RATIO") and k not in (
                   "SECUCODE", "SECURITY_CODE", "SECURITY_NAME_ABBR",
                   "INDUSTRY_CODE", "INDUSTRY_NAME", "MARKET",
                   "SECURITY_TYPE_CODE", "TRADE_MARKET_CODE",
                   "DATE_TYPE_CODE", "REPORT_TYPE_CODE", "DATA_STATE",
                   "ORG_CODE", "TOE_RATIO", "OPERATE_EXPENSE_RATIO",
                   "TOI_RATIO", "OPERATE_PROFIT_RATIO", "PARENT_NETPROFIT_RATIO",
                   "DPN_RATIO", "FCN_RATIO", "INTEREST_NI_RATIO",
                   "EARNED_PREMIUM_RATIO", "OPERATE_INCOME", "INTEREST_NI",
                   "FEE_COMMISSION_NI", "EARNED_PREMIUM", "INVEST_INCOME",
                   "SURRENDER_VALUE", "COMPENSATE_EXPENSE", "REINSURANCE_PREMIUM_CEDED",
                   "MANAGE_EXPENSE_BANK", "FCN_CALCULATE", "INTEREST_NI_CALCULATE",
                   "OPERATE_EXPENSE", "SURRENDER_VALUE", "INTEREST_NI_RATIO",
                   "FCN_RATIO",
               )}
        item = _map_income_row(raw)
        item["ts_code"] = em_code_to_ts_code(em_code)
        item["end_date"] = end_date
        item["ann_date"] = _normalize_date(row.get("NOTICE_DATE"))
        item["report_type"] = "1"
        out.append(item)
    
    # 从新浪补充缺失字段
    sina_income = _fetch_sina_income(em_code)
    if sina_income:
        out = _merge_sina_data(
            out, sina_income,
            ["rd_exp", "assets_impair_loss", "credit_impa_loss",
             "oth_biz_income", "oth_biz_cost", "basic_eps"]
        )
    
    return out


# ─────────────────────────────────────────────────────────────
# 3. 资产负债表 (balance)
# ─────────────────────────────────────────────────────────────
def _map_balance_row(raw: dict) -> dict:
    """映射 EastMoney balance 字段到 Tushare 格式。单位: 元 → 万元。"""
    return {
        # 资产类
        "money_cap": _to_wan(raw.get("MONETARYFUNDS")),
        "accounts_receiv": _to_wan(raw.get("ACCOUNTS_RECE")),
        "inventories": _to_wan(raw.get("INVENTORY")),
        "fix_assets": _to_wan(raw.get("FIXED_ASSET")),
        "cip": _to_wan(raw.get("CIP")),
        "goodwill": _to_wan(raw.get("GOODWILL")),
        "lt_amort_deferred_exp": _to_wan(raw.get("LT_AMORT")),
        # 负债类
        "st_borr": _to_wan(raw.get("ST_LOAN")),
        "lt_borr": _to_wan(raw.get("LT_LOAN")),
        "bond_payable": _to_wan(raw.get("BOND_PAYABLE")),
        "acct_payable": _to_wan(raw.get("ACCOUNTS_PAYABLE")),
        # 合计
        "total_assets": _to_wan(raw.get("TOTAL_ASSETS")),
        "total_liab": _to_wan(raw.get("TOTAL_LIABILITIES")),
        "total_hldr_eqy_exc_min_int": _to_wan(raw.get("TOTAL_EQUITY")),
        # 不直接有的字段
        "minority_int": None,
        "total_hldr_eqy": None,
        "trad_asset": None,
        "notes_receiv": None,
        "oth_receiv": None,
        "prepayment": None,
        "total_cur_assets": None,
        "lt_eqt_invest": None,
        "intang_assets": None,
        "defer_tax_assets": None,
        "total_nca": None,
        "notes_payable": None,
        "contract_liab": None,
        "adv_receipts": None,
        "non_cur_liab_due_1y": None,
        "total_cur_liab": None,
        "total_ncl": None,
        "defer_tax_liab": None,
    }


def get_balance_data(em_code: str, years: int = 10) -> list[dict]:
    """获取资产负债表数据 (年报)，使用 ALL 列避免字段不存在错误。"""
    params = {
        "reportName": "RPT_DMSK_FN_BALANCE",
        "columns": "ALL",
        "filter": f'(SECURITY_CODE="{em_code}")(DATE_TYPE_CODE="001")',
        "pageNumber": 1,
        "pageSize": years,
        "sortTypes": -1,
        "sortColumns": "REPORT_DATE",
        "source": "HSF10",
    }
    result = _em_request(params, cache_key=f"balance:{em_code}")
    if not result or not result.get("data"):
        return []
    rows = result["data"]
    if not isinstance(rows, list):
        rows = [rows]
    out = []
    for row in rows:
        end_date = _normalize_date(row.get("REPORT_DATE"))
        if not end_date or not end_date.endswith("1231"):
            continue
        item = _map_balance_row(row)
        item["ts_code"] = em_code_to_ts_code(em_code)
        item["end_date"] = end_date
        item["ann_date"] = _normalize_date(row.get("NOTICE_DATE"))
        item["report_type"] = "1"
        out.append(item)
    
    # 从新浪补充缺失字段
    sina_balance = _fetch_sina_balance(em_code)
    if sina_balance:
        out = _merge_sina_data(
            out, sina_balance,
            ["cip", "goodwill", "lt_amort_deferred_exp", "st_borr", 
             "lt_borr", "bond_payable", "oth_receiv"]
        )
    
    return out


# ─────────────────────────────────────────────────────────────
# 4. 现金流量表 (cashflow)
# ─────────────────────────────────────────────────────────────
def _map_cashflow_row(raw: dict) -> dict:
    """映射 EastMoney cashflow 字段到 Tushare 格式。单位: 元 → 万元。"""
    return {
        "c_recp_prov_sg_act": _to_wan(raw.get("SALES_SERVICES")),  # 销售商品提供劳务收到的现金
        "n_cashflow_act": _to_wan(raw.get("NETCASH_OPERATE")),     # 经营现金流量净额
        "n_cashflow_inv_act": _to_wan(raw.get("NETCASH_INVEST")),  # 投资现金流量净额
        "n_cash_flows_fnc_act": _to_wan(raw.get("NETCASH_FINANCE")),  # 筹资现金流量净额
        "c_pay_acq_const_fiolta": _to_wan(raw.get("CONSTRUCT_LONG_ASSET")),  # 购建固定资产等
        "n_recp_disp_fiolta": _to_wan(raw.get("DISPOSAL_FIXED_ASSET")),
        "free_cashflow": None,
        "n_cash_end_bal": None,
        "n_cash_beg_bal": None,
    }


def get_cashflow_data(em_code: str, years: int = 10) -> list[dict]:
    """获取现金流量表数据 (年报)，使用 ALL 列避免字段不存在错误。"""
    params = {
        "reportName": "RPT_DMSK_FN_CASHFLOW",
        "columns": "ALL",
        "filter": f'(SECURITY_CODE="{em_code}")(DATE_TYPE_CODE="001")',
        "pageNumber": 1,
        "pageSize": years,
        "sortTypes": -1,
        "sortColumns": "REPORT_DATE",
        "source": "HSF10",
    }
    result = _em_request(params, cache_key=f"cashflow:{em_code}")
    if not result or not result.get("data"):
        return []
    rows = result["data"]
    if not isinstance(rows, list):
        rows = [rows]
    out = []
    for row in rows:
        end_date = _normalize_date(row.get("REPORT_DATE"))
        if not end_date or not end_date.endswith("1231"):
            continue
        item = _map_cashflow_row(row)
        item["ts_code"] = em_code_to_ts_code(em_code)
        item["end_date"] = end_date
        item["ann_date"] = _normalize_date(row.get("NOTICE_DATE"))
        item["report_type"] = "1"
        out.append(item)
    
    # 从新浪补充缺失字段
    sina_cashflow = _fetch_sina_cashflow(em_code)
    if sina_cashflow:
        out = _merge_sina_data(
            out, sina_cashflow,
            ["c_recp_prov_sg_act", "n_recp_disp_fiolta", 
             "n_cash_end_bal", "n_cash_beg_bal"]
        )
    
    # 计算自由现金流 = 经营现金流 - 资本支出
    for item in out:
        n_cashflow_act = item.get("n_cashflow_act")
        c_pay_capex = item.get("c_pay_acq_const_fiolta")
        if n_cashflow_act is not None and c_pay_capex is not None:
            item["free_cashflow"] = n_cashflow_act - c_pay_capex
    
    return out


# ─────────────────────────────────────────────────────────────
# 5. 综合财务指标 — 使用 RPT_F10_FINANCE_MAINFINADATA
# ─────────────────────────────────────────────────────────────
def get_indicator_data(em_code: str, years: int = 10) -> list[dict]:
    """从东方财富 RPT_F10_FINANCE_MAINFINADATA 获取综合财务指标。
    
    字段映射:
    - XSMLL → grossprofit_margin (毛利率)
    - XSJLL → netprofit_margin (净利率)
    - ROEJQ → roe
    - ROEKCJQ → roe_waa (扣非ROE)
    - CHZZL → inv_turn (存货周转率)
    - YSZKZZL → ar_turn (应收周转率)
    - ZCFZL → debt_to_assets (资产负债率)
    - FCFF_BACK → fcff (自由现金流)
    - INTEREST_DEBT_RATIO → interestdebt_ratio (有息负债比)
    - MGJYXJJE → ocfps (每股经营CF)
    - EPSJB → basic_eps (基本EPS)
    - BPS → bps
    - KCFJCXSYJLR → deduct_net_profit (扣非净利润)
    - NCO_NETPROFIT → ocfps 近似
    - NCO_OP → 
    - XSJXLYYSR → 
    - DJD_DPNP_YOY → netprofit_yoy
    - DJD_TOI_YOY → revenue_yoy
    """
    params = {
        "reportName": "RPT_F10_FINANCE_MAINFINADATA",
        "columns": (
            "REPORT_DATE,NOTICE_DATE,"
            "XSMLL,XSJLL,ROEJQ,ROEKCJQ,"
            "CHZZL,YSZKZZL,ZCFZL,"
            "FCFF_BACK,INTEREST_DEBT_RATIO,"
            "MGJYXJJE,EPSJB,BPS,"
            "KCFJCXSYJLR,"
            "NCO_NETPROFIT,NCO_OP,XSJXLYYSR,"
            "DJD_DPNP_YOY,DJD_TOI_YOY,"
            "TOTALOPERATEREVE,TOTAL_ASSETS_PK,TOTAL_EQUITY_PK,"
            "LIABILITY,STAFF_NUM"
        ),
        "filter": f'(SECURITY_CODE="{em_code}")',
        "pageNumber": 1,
        "pageSize": years * 4 + 5,  # Get more rows since interface returns all quarters
        "sortTypes": -1,
        "sortColumns": "REPORT_DATE",
        "source": "HSF10",
    }
    result = _em_request(params, cache_key=f"indicators:{em_code}")
    if not result or not result.get("data"):
        return []
    
    rows = result["data"]
    if not isinstance(rows, list):
        rows = [rows]
    
    ts_code = em_code_to_ts_code(em_code)
    
    # 收集所有年报数据
    annual_data = []
    quarterly_data = {}
    
    for row in rows:
        end_date = _normalize_date(row.get("REPORT_DATE"))
        if not end_date:
            continue
        
        # 分离年报和季报数据
        if end_date.endswith("1231"):
            annual_data.append((end_date, row))
        else:
            # 保存季报数据用于后续YoY计算
            year = end_date[:4]
            if year not in quarterly_data:
                quarterly_data[year] = []
            quarterly_data[year].append((end_date, row))
    
    # 按年份分组年报数据
    annual_by_year = {}
    for end_date, row in annual_data:
        year = end_date[:4]
        annual_by_year[year] = row
    
    # 选择最近 N 年的年报数据
    sorted_years = sorted(annual_by_year.keys(), reverse=True)[:years]
    
    out = []
    for i, year in enumerate(sorted_years):
        row = annual_by_year[year]
        end_date = f"{year}1231"
        
        # 转换字段值
        def safe(val):
            if val is None or val == "" or val == "--":
                return None
            try:
                f = float(val)
                if math.isnan(f) or math.isinf(f):
                    return None
                return f
            except:
                return None
        
        # 有息负债 = 有息负债比 * 总资产
        interestdebt_ratio = safe(row.get("INTEREST_DEBT_RATIO"))
        total_assets_pk = safe(row.get("TOTAL_ASSETS_PK"))
        interestdebt = None
        if interestdebt_ratio is not None and total_assets_pk is not None:
            # TOTAL_ASSETS_PK 是元，除以10000转为万元，再乘以百分比
            interestdebt = total_assets_pk / 10000 * interestdebt_ratio / 100
        
        # ROE、净利润率、资产负债率通常已经是百分比形式
        roe = safe(row.get("ROEJQ"))
        roe_waa = safe(row.get("ROEKCJQ"))
        grossprofit_margin = safe(row.get("XSMLL"))
        netprofit_margin = safe(row.get("XSJLL"))
        debt_to_assets = safe(row.get("ZCFZL"))
        
        # YoY数据 - API的YoY值不准确，设为None
        # 后续可以从income数据推导或在报告中说明
        revenue_yoy = None
        netprofit_yoy = None
        
        # 每股指标
        basic_eps = safe(row.get("EPSJB"))
        bps = safe(row.get("BPS"))
        ocfps = safe(row.get("MGJYXJJE"))
        
        # 扣非净利润
        deduct_net_profit = safe(row.get("KCFJCXSYJLR"))
        
        # 自由现金流（万元）
        fcff = safe(row.get("FCFF_BACK"))
        
        # 周转率
        inv_turn = safe(row.get("CHZZL"))
        ar_turn = safe(row.get("YSZKZZL"))
        
        out.append({
            "ts_code": ts_code,
            "end_date": end_date,
            "ann_date": _normalize_date(row.get("NOTICE_DATE")),
            "roe": roe,
            "roe_waa": roe_waa,
            "grossprofit_margin": grossprofit_margin,
            "netprofit_margin": netprofit_margin,
            "rd_exp": None,
            "current_ratio": None,
            "quick_ratio": None,
            "assets_turn": None,
            "inv_turn": inv_turn,
            "ar_turn": ar_turn,
            "debt_to_assets": debt_to_assets,
            "revenue_yoy": revenue_yoy,
            "netprofit_yoy": netprofit_yoy,
            "ocfps": ocfps,
            "bps": bps,
            "profit_dedt": None,
            "ebitda": None,
            "fcff": fcff,
            "netdebt": None,
            "interestdebt": interestdebt,
            "extra_item": None,
            "deduct_item": deduct_net_profit,
        })
    
    return out


def _derive_indicators(
    income_list: list[dict],
    balance_list: list[dict],
    cashflow_list: list[dict],
    ts_code: str,
) -> list[dict]:
    """从 income/balance/cashflow 数据推导财务指标（备用，当 RPT_F10_FINANCE_MAINFINADATA 失败时）。"""
    # 构建 end_date → balance / cashflow 的索引
    bal_map = {r["end_date"]: r for r in balance_list}
    cf_map = {r["end_date"]: r for r in cashflow_list}
    inc_map = {r["end_date"]: r for r in income_list}

    # 按日期升序排列 (最早→最新)，便于计算 YoY
    sorted_dates = sorted(income_list, key=lambda x: x["end_date"])
    sorted_dates.reverse()  # 降序

    indicators = []
    prev_inc = None
    for inc in income_list:
        end_date = inc["end_date"]
        bal = bal_map.get(end_date, {})
        cf = cf_map.get(end_date, {})

        revenue = inc.get("revenue")
        oper_cost = inc.get("oper_cost")
        n_income_attr_p = inc.get("n_income_attr_p")
        total_eq = bal.get("total_hldr_eqy_exc_min_int") or bal.get("total_assets")
        total_assets = bal.get("total_assets")
        total_liab = bal.get("total_liab")
        n_cashflow_act = cf.get("n_cashflow_act")
        c_pay_capex = cf.get("c_pay_acq_const_fiolta")
        st_borr = bal.get("st_borr") or 0
        lt_borr = bal.get("lt_borr") or 0
        bond_payable = bal.get("bond_payable") or 0

        # 毛利率
        if revenue and oper_cost and revenue != 0:
            grossprofit_margin = (revenue - oper_cost) / revenue * 100
        else:
            grossprofit_margin = None

        # 净利率
        if revenue and n_income_attr_p and revenue != 0:
            netprofit_margin = n_income_attr_p / revenue * 100
        else:
            netprofit_margin = None

        # ROE
        if total_eq and n_income_attr_p and total_eq != 0:
            roe = n_income_attr_p / total_eq * 100
        else:
            roe = None

        # 资产负债率
        if total_assets and total_liab and total_assets != 0:
            debt_to_assets = total_liab / total_assets * 100
        else:
            debt_to_assets = None

        # FCFF = 经营现金流 - 资本支出
        if n_cashflow_act is not None and c_pay_capex is not None:
            fcff = n_cashflow_act - c_pay_capex
        else:
            fcff = None

        # 有息负债
        interestdebt = st_borr + lt_borr + bond_payable

        # YoY (需要上一期)
        prev_rev = prev_inc.get("revenue") if prev_inc else None
        prev_ni = prev_inc.get("n_income_attr_p") if prev_inc else None
        if revenue and prev_rev and prev_rev != 0:
            revenue_yoy = (revenue - prev_rev) / abs(prev_rev) * 100
        else:
            revenue_yoy = None
        if n_income_attr_p and prev_ni and prev_ni != 0:
            netprofit_yoy = (n_income_attr_p - prev_ni) / abs(prev_ni) * 100
        else:
            netprofit_yoy = None

        prev_inc = inc

        indicators.append({
            "ts_code": ts_code,
            "end_date": end_date,
            "ann_date": inc.get("ann_date"),
            "roe": roe,
            "roe_waa": roe,  # 东方财富 ROE 就是加权 ROE
            "grossprofit_margin": grossprofit_margin,
            "netprofit_margin": netprofit_margin,
            "rd_exp": inc.get("rd_exp"),
            "current_ratio": None,  # 需要期初数据
            "quick_ratio": None,
            "assets_turn": None,
            "inv_turn": None,
            "ar_turn": None,
            "debt_to_assets": debt_to_assets,
            "revenue_yoy": revenue_yoy,
            "netprofit_yoy": netprofit_yoy,
            "ocfps": None,
            "bps": None,
            "profit_dedt": None,
            "ebitda": None,
            "fcff": fcff,
            "netdebt": None,
            "interestdebt": interestdebt if interestdebt > 0 else None,
            "extra_item": None,
            "deduct_item": inc.get("deduct_n_income"),
        })
    return indicators


# ─────────────────────────────────────────────────────────────
# 6. 审计意见 (audit)
# ─────────────────────────────────────────────────────────────
def get_audit_data(em_code: str) -> list[dict]:
    """从东方财富 F10 年报审计意见页面抓取审计意见。

    策略:
    1. 尝试东方财富 datacenter RPT_F10_AUDIT_OPINION
    2. 尝试巨潮资讯 API
    3. 返回 SKIP 标记（在年报PDF提取阶段处理）
    """
    # 方式1: 尝试东方财富 F10 审计意见接口
    params = {
        "reportName": "RPT_F10_AUDIT_OPINION",
        "columns": "SECUCODE,SECURITY_CODE,REPORT_DATE,NOTICE_DATE,"
                    "AUDIT_OPINION,AUDIT_FIRM,AUDIT_FEE",
        "filter": f'(SECURITY_CODE="{em_code}")',
        "pageNumber": 1,
        "pageSize": 10,
        "sortTypes": -1,
        "sortColumns": "REPORT_DATE",
        "source": "HSF10",
    }
    result = _em_request(params, cache_key=f"audit:{em_code}")
    if result and result.get("data"):
        rows = result["data"]
        if not isinstance(rows, list):
            rows = [rows]
        out = []
        for row in rows:
            end_date = _normalize_date(row.get("REPORT_DATE"))
            if not end_date:
                continue
            out.append({
                "ts_code": em_code_to_ts_code(em_code),
                "ann_date": _normalize_date(row.get("NOTICE_DATE")),
                "end_date": end_date,
                "audit_result": _safe_str(row.get("AUDIT_OPINION")),
                "audit_agency": _safe_str(row.get("AUDIT_FIRM")),
                "audit_fees": _safe_num(row.get("AUDIT_FEE")),
            })
        if out:
            return out

    # 方式2: 尝试巨潮资讯 API (审计意见)
    try:
        cninfo_url = (
            f"https://www.cninfo.com.cn/new/data/szplatenotice.json?"
            f"stock={em_code}"
        )
        resp = requests.get(
            cninfo_url,
            headers={"User-Agent": _HEADERS["User-Agent"]},
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            notices = data.get("notices", [])
            audit_rows = []
            for note in notices:
                title = _safe_str(note.get("notice_title", ""))
                # 找含"审计报告"的年报
                if "审计报告" in title or "年报" in title:
                    end_date = _normalize_date(note.get("bd_datetime"))
                    if end_date and end_date.endswith("1231"):
                        audit_rows.append({
                            "ts_code": em_code_to_ts_code(em_code),
                            "ann_date": _normalize_date(note.get("notice_date")),
                            "end_date": end_date,
                            "audit_result": "SKIP",  # 无法从标题判断审计意见
                            "audit_agency": "",
                            "audit_fees": None,
                        })
            if audit_rows:
                return audit_rows
    except Exception:
        pass

    # 无法获取时返回 SKIP 标记
    return []


# ─────────────────────────────────────────────────────────────
# 7. 前十大股东 (holders) — 从 emweb API 获取
# ─────────────────────────────────────────────────────────────
def get_holder_data(em_code: str) -> list[dict]:
    """从东方财富 emweb API 获取前十大股东数据。

    API: https://emweb.securities.eastmoney.com/PC_HSF10/ShareholderResearch/PageAjax?code=SH600519
    """
    ts_code = em_code_to_ts_code(em_code)
    
    # 确定市场前缀
    if em_code.startswith("6"):
        market_prefix = "SH"
    else:
        market_prefix = "SZ"
    
    params = {"code": f"{market_prefix}{em_code}"}
    
    data = _emweb_request(
        _EMWEB_URL,
        params,
        cache_key=f"holders:{em_code}"
    )
    
    if not data:
        return []
    
    out = []
    
    # 获取十大股东数据 (sdgd) - 字段名是 sdgd
    sdgd_list = data.get("sdgd") or []
    if not isinstance(sdgd_list, list):
        sdgd_list = [sdgd_list] if sdgd_list else []
    
    for item in sdgd_list:
        if not item:
            continue
        end_date = _normalize_date(item.get("END_DATE"))
        if not end_date:
            continue
        
        holder_name = _safe_str(item.get("HOLDER_NAME"))
        if not holder_name:
            continue
        
        # 持股数量 (股)
        raw_amount = item.get("HOLD_NUM")
        hold_amount = _safe_num(raw_amount)
        
        # 持股比例 - 已经是百分比形式 (如 54.4 表示 54.4%)
        raw_ratio = item.get("HOLD_NUM_RATIO")
        if isinstance(raw_ratio, str):
            ratio = _safe_num(raw_ratio.replace("%", ""))
        else:
            ratio = _safe_num(raw_ratio)
        # HOLD_NUM_RATIO 已经是百分比，不需要再乘以100
        
        out.append({
            "end_date": end_date,
            "holder_name": holder_name,
            "hold_amount": hold_amount,
            "hold_ratio": ratio,
        })
    
    # 去重并排序
    if out:
        # 按日期降序，日期内按持股比例降序
        out.sort(key=lambda x: (x["end_date"], x.get("hold_ratio") or 0), reverse=True)
        return out
    
    return []


# ─────────────────────────────────────────────────────────────
# 8. 同行对比 (peers) — 使用东方财富行业分类接口
# ─────────────────────────────────────────────────────────────
def get_peer_data(em_code: str, industry: str,
                   peer_industry_raw: str = "") -> dict:
    """获取同行业公司财务指标用于对比。

    策略:
    1. 优先用完整行业路径 (EM2016) 精确匹配
    2. 备用: 用 BOARD_NAME_LEVEL 精确匹配
    3. 返回 peer 对比数据
    """
    if not industry and not peer_industry_raw:
        return {"industry": industry or peer_industry_raw, "peers": []}

    ts_code = em_code_to_ts_code(em_code)
    display_industry = industry or peer_industry_raw

    # 尝试精确匹配 EM2016 完整路径
    peer_codes = set()
    rows_by_code = {}  # code -> row for name lookup

    for use_board_level in [False, True]:
        if peer_codes:
            break  # Already found peers
        industry_param = peer_industry_raw
        if not industry_param:
            continue

        # 使用精确匹配而非 LIKE（LIKE 对中文字符有时不工作）
        col = "BOARD_NAME_LEVEL" if use_board_level else "EM2016"
        try:
            industry_params = {
                "reportName": "RPT_F10_BASIC_ORGINFO",
                "columns": "SECURITY_CODE,SECURITY_NAME_ABBR,EM2016,BOARD_NAME_LEVEL",
                "filter": f'({col}="{industry_param}")',
                "pageNumber": 1,
                "pageSize": 50,
                "source": "HSF10",
            }
            ind_result = _em_request(
                industry_params,
                cache_key=f"industry_exact:{col}:{industry_param}",
            )
            if ind_result and ind_result.get("data"):
                rows = ind_result["data"]
                if not isinstance(rows, list):
                    rows = [rows]
                for r in rows:
                    code = r.get("SECURITY_CODE")
                    if code and code != em_code:
                        peer_codes.add(code)
                        rows_by_code[code] = r
        except Exception as e:
            print(f"Warning: Peer search failed for {col}: {e}", file=sys.stderr)
            continue

    if not peer_codes:
        return {"industry": display_industry, "peers": []}

    peers_data = []
    for peer_code in list(peer_codes)[:20]:  # Limit to 20
        peer_ts = em_code_to_ts_code(peer_code)
        income_rows = get_income_data(peer_code, years=1)
        if not income_rows:
            continue
        latest = income_rows[0]
        revenue = latest.get("revenue")
        oper_cost = latest.get("oper_cost")
        n_income_attr_p = latest.get("n_income_attr_p")

        # 计算 grossprofit_margin / netprofit_margin
        gm = None
        nm = None
        if revenue and oper_cost and revenue != 0:
            gm = (revenue - oper_cost) / revenue * 100
        if revenue and n_income_attr_p and revenue != 0:
            nm = n_income_attr_p / revenue * 100

        peer_row = rows_by_code.get(peer_code, {})
        peers_data.append({
            "ts_code": peer_ts,
            "name": _safe_str(peer_row.get("SECURITY_NAME_ABBR", "")),
            "end_date": latest.get("end_date", ""),
            "grossprofit_margin": gm,
            "netprofit_margin": nm,
            "debt_to_assets": None,
            "roe": None,
            "assets_turn": None,
            "inv_turn": None,
            "ar_turn": None,
        })

    return {"industry": display_industry, "peers": peers_data}


# ─────────────────────────────────────────────────────────────
# 主入口: 收集全部数据
# ─────────────────────────────────────────────────────────────
def collect_eastmoney_data(stock_code: str, years: int = 10) -> dict:
    """收集指定股票的全部财报数据 (使用东方财富免费 API)。

    Args:
        stock_code: 股票代码，支持纯数字 (600519) 或 Tushare 格式 (600519.SH)
        years: 获取近 N 年年报

    Returns:
        与 Tushare minesweeper_data.py 完全一致的 JSON 结构
    """
    # 规范代码格式
    if re.match(r"^\d{6}\.(SH|SZ)$", stock_code):
        em_code = stock_code.split(".")[0]
    elif re.match(r"^\d{6}$", stock_code):
        em_code = stock_code
    else:
        raise ValueError(f"Unsupported stock code format: {stock_code}")

    ts_code = em_code_to_ts_code(em_code)

    print(f"Collecting EastMoney data for {ts_code}...", file=sys.stderr)

    # 1. 基本信息
    stock_info = get_stock_info(em_code)
    print(f"  [1/8] Basic info: {stock_info.get('name', '?')}", file=sys.stderr)

    # 2. 审计意见
    audit = get_audit_data(em_code)
    print(f"  [2/8] Audit data: {len(audit)} records", file=sys.stderr)

    # 3. 利润表
    income = get_income_data(em_code, years)
    print(f"  [3/8] Income statement: {len(income)} years", file=sys.stderr)

    # 4. 资产负债表
    balance = get_balance_data(em_code, years)
    print(f"  [4/8] Balance sheet: {len(balance)} years", file=sys.stderr)

    # 5. 现金流量表
    cashflow = get_cashflow_data(em_code, years)
    print(f"  [5/8] Cash flow: {len(cashflow)} years", file=sys.stderr)

    # 6. 财务指标 (优先从 RPT_F10_FINANCE_MAINFINADATA 获取)
    indicators = get_indicator_data(em_code, years)
    if not indicators:
        # 备用：自己推导
        indicators = _derive_indicators(income, balance, cashflow, ts_code)
    print(f"  [6/8] Financial indicators: {len(indicators)} years", file=sys.stderr)

    # 7. 股东数据
    holders = get_holder_data(em_code)
    print(f"  [7/8] Shareholders: {len(holders)} records", file=sys.stderr)

    # 8. 同行对比
    industry = stock_info.get("industry", "")
    peer_industry_raw = stock_info.get("_peer_industry_raw", "")
    print(f"  [8/8] Peer comparison for industry: {industry}...", file=sys.stderr)
    peers = get_peer_data(em_code, industry, peer_industry_raw)
    print(f"  [8/8] Peer data: {len(peers.get('peers', []))} peers",
          file=sys.stderr)

    return {
        "stock_info": stock_info,
        "audit": audit,
        "income": income,
        "balance": balance,
        "cashflow": cashflow,
        "indicators": indicators,
        "holders": holders,
        "peers": peers,
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="东方财富财报数据获取")
    parser.add_argument("--stock-code", required=True, help="股票代码")
    parser.add_argument("--years", type=int, default=10, help="年数")
    args = parser.parse_args()
    data = collect_eastmoney_data(args.stock_code, args.years)
    print(json.dumps(data, ensure_ascii=False, indent=2))
