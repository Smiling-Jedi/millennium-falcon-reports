#!/usr/bin/env python3
"""
v25 设计稿还原 — 自动化质量扫描脚本
检查所有生成页面的结构完整性、数据质量、移动端适配。
输出问题清单，按严重程度排序。
"""
import json, os, re, sys
from pathlib import Path
from collections import Counter

REPORTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(REPORTS_DIR, ".."))

issues = []  # [(severity, page, check_name, detail)]

def issue(severity, page, check, detail):
    issues.append((severity, page, check, detail))

# ═══════════════════════════════════════════════════════════
# 1. 首页 index.html 扫描
# ═══════════════════════════════════════════════════════════
def scan_index():
    path = os.path.join(REPORTS_DIR, "index.html")
    if not os.path.exists(path):
        issue("P0", "index.html", "文件存在", "index.html 不存在！")
        return
    html = Path(path).read_text(encoding="utf-8")

    # 1a. 页面结构
    for tag in ["masthead", "tabs", "snapshot-banner", "side-idx", "panel-us", "panel-a", "panel-hk", "footer"]:
        if f'class="{tag}"' not in html and f'id="{tag}"' not in html and f'id="panel-"' not in html:
            pass  # 部分用动态生成
    if '</html>' not in html:
        issue("P0", "index.html", "结构-闭合", "缺少 </html>")

    # 1b. snapshotData JS
    if "const snapshotData" not in html:
        issue("P0", "index.html", "JS-snapshotData", "缺少 snapshotData 变量")

    # 1c. 卡片三入口结构
    cards_with_report_link = len(re.findall(r'class="card-report-link"', html))
    cards_with_more = len(re.findall(r'class="card-more"', html))
    cards_with_main_link = len(re.findall(r'class="card-main-link"', html))
    print(f"  首页卡片: main_link={cards_with_main_link} report_link={cards_with_report_link} more={cards_with_more}")
    if cards_with_main_link == 0:
        issue("P0", "index.html", "卡片-入口", "卡片缺少 card-main-link（交易计划入口）")
    if cards_with_report_link == 0:
        issue("P0", "index.html", "卡片-入口", "卡片缺少 card-report-link（最新日报入口）")
    if cards_with_more == 0:
        issue("P0", "index.html", "卡片-入口", "卡片缺少 card-more（全部日报入口）")

    # 1d. 卡片无效 href 属性（div 上不应有 href）
    invalid_hrefs = re.findall(r'<div[^>]*href="stock_', html)
    if invalid_hrefs:
        issue("P0", "index.html", "卡片-无效href", f"{len(invalid_hrefs)} 个卡片 div 仍有无效 href 属性")

    # 1e. plan-key 分布
    plan_keys = Counter(re.findall(r'<span class="plan-key">([^<]+)</span>', html))
    print(f"  首页 plan-key 分布: {dict(plan_keys)}")
    # 检查是否有 A 型股票用了「买入」而不是「持仓」
    buy_count = plan_keys.get("买入", 0)
    position_count = plan_keys.get("持仓", 0)
    if position_count > buy_count:
        issue("P1", "index.html", "卡片-plan-key",
              f"「持仓」({position_count}) 多于「买入」({buy_count})，部分股票未提取到 PEG/PE 数据")

    # 1f. 状态标签
    status_tags = Counter(re.findall(r'<span class="card-status ([^"]+)">([^<]+)</span>', html))
    watch_count = sum(1 for cls, text in re.findall(r'<span class="card-status ([^"]+)">([^<]+)</span>', html) if cls == "watch")
    hold_count = sum(1 for cls, text in re.findall(r'<span class="card-status ([^"]+)">([^<]+)</span>', html) if cls == "hold")
    print(f"  首页状态标签: watch={watch_count} hold={hold_count} add={sum(1 for c,t in re.findall(r'<span class="card-status ([^"]+)">([^<]+)</span>', html) if c=='add')} stop={sum(1 for c,t in re.findall(r'<span class="card-status ([^"]+)">([^<]+)</span>', html) if c=='stop')}")

    # 1g. 移动端 CSS 检查
    if "@media (max-width: 720px)" not in html:
        issue("P1", "index.html", "移动端-断点", "缺少 @media (max-width: 720px) 响应式断点")
    if ".mobile-tabs" not in html:
        issue("P1", "index.html", "移动端-tabs", "缺少 .mobile-tabs 样式")
    if "display: none" not in html or "display: flex" not in html:
        pass  # 太泛

    # 1h. 盘中速览入口
    snapshot_links = re.findall(r'snapshot_\w+\.html', html)
    print(f"  首页 snapshot 链接: {snapshot_links[:5]}")

    # 1i. 股票名显示为原始 code 的卡片
    code_like_names = re.findall(r'<span class="card-name">([A-Z]{2,5}\.[A-Z]{2,10})</span>', html)
    if code_like_names:
        issue("P1", "index.html", "卡片-名称", f"{len(code_like_names)} 只股票名称显示为原始代码: {code_like_names}")

# ═══════════════════════════════════════════════════════════
# 2. 个股交易计划页扫描
# ═══════════════════════════════════════════════════════════
def scan_stock_pages():
    stock_files = sorted(Path(REPORTS_DIR).glob("stock_*.html"))
    # 排除 stock_reports_* 和 stock_mock_*
    stock_files = [f for f in stock_files if "stock_reports" not in f.name and "stock_mock" not in f.name]
    print(f"\n  个股页: {len(stock_files)} 个文件")

    stats = {"stock_hd": 0, "status_bar_grid": 0, "daily_check": 0, "plan_card": 0,
             "plan_section": 0, "sig_grid": 0, "back_nav": 0}
    empty_plan = []
    missing_sections = []

    for f in stock_files:
        html = f.read_text(encoding="utf-8")
        name = f.stem.replace("stock_", "")

        # 结构检查
        if "stock-hd" in html: stats["stock_hd"] += 1
        else: missing_sections.append((name, "stock-hd"))

        if "status-bar" in html and "status-item" in html: stats["status_bar_grid"] += 1
        else: missing_sections.append((name, "status-bar"))

        if "daily-check" in html: stats["daily_check"] += 1
        if "plan-card" in html: stats["plan_card"] += 1
        if "plan-section" in html: stats["plan_section"] += 1
        if "sig-grid" in html: stats["sig_grid"] += 1
        if "back-nav" in html: stats["back_nav"] += 1

        # 空内容检查
        # plan-card 为空
        plan_card_match = re.search(r'<div class="plan-card">(.*?)</div>\s*</div>', html, re.S)
        if plan_card_match:
            content = plan_card_match.group(1).strip()
            if not content or len(content) < 50:
                empty_plan.append(name)

        # 状态条关键字段
        status_items = re.findall(r'<span class="status-item">(.+?)</span>', html)
        if not status_items:
            missing_sections.append((name, "status-items-empty"))

    print(f"  个股页结构: {stats}")
    if empty_plan:
        issue("P0", "个股页", "plan-card-空内容", f"{len(empty_plan)} 个页面交易计划为空: {empty_plan}")
    missing_stock_hd = [n for n, s in missing_sections if s == "stock-hd"]
    if missing_stock_hd:
        issue("P0", "个股页", "stock-hd-缺失", f"{len(missing_stock_hd)} 个页面缺股票头图")
    missing_sb = [n for n, s in missing_sections if s == "status-bar"]
    if missing_sb:
        issue("P1", "个股页", "status-bar-缺失", f"{len(missing_sb)} 个页面缺状态条")

    # 统计 plan-section 类型
    all_sections = Counter()
    for f in stock_files:
        html = f.read_text(encoding="utf-8")
        secs = re.findall(r'<div class="ps-label">([^<]+)</div>', html)
        all_sections.update(secs)
    print(f"  个股页 section 类型: {dict(all_sections)}")

    # 检查哪些股票只有很少 section
    for f in stock_files:
        html = f.read_text(encoding="utf-8")
        secs = re.findall(r'<div class="ps-label">([^<]+)</div>', html)
        if len(secs) <= 1:
            issue("P1", "个股页", f"section-少-{f.stem}", f"只有 {len(secs)} 个 section: {secs}")

# ═══════════════════════════════════════════════════════════
# 3. 日报汇总页扫描
# ═══════════════════════════════════════════════════════════
def scan_stock_reports():
    files = sorted(Path(REPORTS_DIR).glob("stock_reports_*.html"))
    print(f"\n  日报汇总页: {len(files)} 个文件")

    stats = {"stock_hd": 0, "status_bar": 0, "report_list": 0, "back_nav": 0}
    for f in files:
        html = f.read_text(encoding="utf-8")
        if "stock-hd" in html: stats["stock_hd"] += 1
        if "status-bar" in html: stats["status_bar"] += 1
        if "report-list" in html: stats["report_list"] += 1
        if "back-nav" in html: stats["back_nav"] += 1
    print(f"  日报汇总页结构: {stats}")

# ═══════════════════════════════════════════════════════════
# 4. 盘中速览页扫描
# ═══════════════════════════════════════════════════════════
def scan_snapshots():
    for mkt in ["us", "a", "hk"]:
        path = os.path.join(REPORTS_DIR, f"snapshot_{mkt}.html")
        if not os.path.exists(path):
            issue("P1", f"snapshot_{mkt}", "文件存在", "文件不存在")
            continue
        html = Path(path).read_text(encoding="utf-8")
        has_list = "snapshot-list" in html
        has_back = "back-nav" in html
        items = len(re.findall(r'<li>', html))
        print(f"  snapshot_{mkt}: list={has_list} back={has_back} items={items}")

# ═══════════════════════════════════════════════════════════
# 5. 运行并输出
# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 60)
    print("千年隼 v25 设计稿还原 — 质量扫描")
    print("=" * 60)

    print("\n📄 首页 index.html")
    scan_index()

    print("\n📄 个股交易计划页 stock_*.html")
    scan_stock_pages()

    print("\n📄 日报汇总页 stock_reports_*.html")
    scan_stock_reports()

    print("\n📄 盘中速览页 snapshot_*.html")
    scan_snapshots()

    # 输出问题
    print("\n" + "=" * 60)
    print(f"问题清单 ({len(issues)} 个)")
    print("=" * 60)
    if not issues:
        print("✅ 未发现问题")
    else:
        for sev, page, check, detail in sorted(issues):
            print(f"  [{sev}] {page} | {check}")
            print(f"       {detail}")
