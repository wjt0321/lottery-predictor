#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据更新脚本
从500彩票网获取最新双色球开奖数据并增量更新
"""

import json
import os
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


DATA_FILE = "lottery_data.json"
FETCH_TARGET_RECORDS = 220
MAX_FETCH_PAGES = 8


def build_date_range(records):
    """统一生成从旧到新的日期范围文本。"""
    if not records:
        return ""
    ordered = sorted(records, key=lambda x: x['date'])
    return f"{ordered[0]['date']} 至 {ordered[-1]['date']}"


def load_existing_data():
    """加载现有数据"""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"metadata": {}, "records": []}


def save_data(records):
    """保存数据"""
    records = sorted(records, key=lambda x: x['date'], reverse=True)
    data = {
        "metadata": {
            "total_records": len(records),
            "date_range": build_date_range(records),
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": "500.com-real",
            "is_real": True
        },
        "records": records
    }
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def fetch_from_500():
    """从500彩票网抓取数据"""
    records_by_period = {}

    def parse_html_table(html_text):
        parsed = {}
        soup = BeautifulSoup(html_text, 'html.parser')
        rows = soup.select('#tdata tr')
        for row in rows:
            cells = [td.get_text(strip=True) for td in row.select('td')]
            if len(cells) < 16:
                continue
            period = cells[0]
            reds = cells[1:7]
            blue = cells[7]
            date_text = cells[15] if len(cells) > 15 else ''
            if not period.isdigit():
                continue
            if not all(x.isdigit() for x in reds) or not blue.isdigit() or not date_text:
                continue
            full_period = f"20{period}"
            
            # 解析额外数据（销售额、奖池、中奖注数等）
            extra_data = {}
            try:
                # 销售额通常在第8列
                if len(cells) > 8:
                    sales_text = cells[8].replace(',', '').replace('元', '').strip()
                    if sales_text.isdigit():
                        extra_data['sales'] = int(sales_text)
                # 奖池通常在第9列
                if len(cells) > 9:
                    pool_text = cells[9].replace(',', '').replace('元', '').strip()
                    if pool_text.isdigit():
                        extra_data['pool'] = int(pool_text)
                # 一等奖注数通常在第10列
                if len(cells) > 10:
                    first_prize_text = cells[10].replace(',', '').strip()
                    if first_prize_text.isdigit():
                        extra_data['first_prize_count'] = int(first_prize_text)
                # 一等奖金额通常在第11列
                if len(cells) > 11:
                    first_prize_amount = cells[11].replace(',', '').replace('元', '').strip()
                    if first_prize_amount.isdigit():
                        extra_data['first_prize_amount'] = int(first_prize_amount)
            except Exception:
                pass
            
            parsed[full_period] = {
                "period": full_period,
                "date": date_text,
                "red_balls": sorted(int(x) for x in reds),
                "blue_ball": int(blue),
            }
            # 合并额外数据
            parsed[full_period].update(extra_data)
        return parsed

    try:
        print("🌐 正在访问500彩票网历史接口...")
        base_url = 'https://datachart.500.com/ssq/history/newinc/history.php'
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://datachart.500.com/ssq/history/history.shtml",
        }
        first_html = requests.get(base_url, headers=headers, timeout=30).text
        first_soup = BeautifulSoup(first_html, 'html.parser')
        end_issue = first_soup.select_one('input[name="end"]')
        end_value = end_issue.get('value', '').strip() if end_issue else ''
        if end_value.isdigit():
            start_value = max(3001, int(end_value) - 2000)
            full_url = f"{base_url}?start={start_value}&end={end_value}"
            all_html = requests.get(full_url, headers=headers, timeout=30).text
            records_by_period.update(parse_html_table(all_html))
            print(f"📊 历史接口解析 {len(records_by_period)} 条记录")
            if len(records_by_period) >= FETCH_TARGET_RECORDS:
                return list(records_by_period.values())
        else:
            records_by_period.update(parse_html_table(first_html))
    except Exception as e:
        print(f"   历史接口抓取失败: {e}")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            )
            page = context.new_page()
            
            print("🌐 正在访问500彩票网...")
            page.goto('https://datachart.500.com/ssq/history/history.shtml', 
                     wait_until='networkidle', timeout=60000)
            
            # 等待数据表格加载
            page.wait_for_selector('#tdata', timeout=20000)
            page.wait_for_timeout(2000)
            
            # 尝试点击"最近100期"链接获取更多数据
            try:
                # 查找包含"最近100期"的链接并点击
                links = page.query_selector_all('a')
                for link in links:
                    text = link.inner_text().strip()
                    if '最近100期' in text or '100期' in text:
                        print("📋 点击'最近100期'...")
                        link.click()
                        page.wait_for_timeout(3000)
                        break
            except Exception as e:
                print(f"   点击100期链接失败: {e}")
            
            print("📊 正在提取数据...")
            for page_index in range(MAX_FETCH_PAGES):
                rows = page.query_selector_all('#tdata tr')
                for row in rows:
                    try:
                        cells = row.query_selector_all('td')
                        if len(cells) >= 16:
                            period = cells[0].inner_text().strip()
                            red_balls = []
                            for j in range(1, 7):
                                ball_text = cells[j].inner_text().strip()
                                if ball_text.isdigit():
                                    red_balls.append(int(ball_text))
                            blue_text = cells[7].inner_text().strip()
                            blue_ball = int(blue_text) if blue_text.isdigit() else 0
                            date_text = cells[15].inner_text().strip() if len(cells) > 15 else ''
                            if period and len(red_balls) == 6 and blue_ball > 0 and date_text:
                                full_period = f"20{period}"
                                record_data = {
                                    "period": full_period,
                                    "date": date_text,
                                    "red_balls": sorted(red_balls),
                                    "blue_ball": blue_ball
                                }
                                # 尝试抓取额外数据
                                try:
                                    if len(cells) > 8:
                                        sales_text = cells[8].inner_text().strip().replace(',', '').replace('元', '')
                                        if sales_text.isdigit():
                                            record_data['sales'] = int(sales_text)
                                    if len(cells) > 9:
                                        pool_text = cells[9].inner_text().strip().replace(',', '').replace('元', '')
                                        if pool_text.isdigit():
                                            record_data['pool'] = int(pool_text)
                                    if len(cells) > 10:
                                        first_prize_text = cells[10].inner_text().strip().replace(',', '')
                                        if first_prize_text.isdigit():
                                            record_data['first_prize_count'] = int(first_prize_text)
                                    if len(cells) > 11:
                                        first_prize_amount = cells[11].inner_text().strip().replace(',', '').replace('元', '')
                                        if first_prize_amount.isdigit():
                                            record_data['first_prize_amount'] = int(first_prize_amount)
                                except Exception:
                                    pass
                                records_by_period[full_period] = record_data
                    except Exception:
                        continue
                print(f"   第{page_index + 1}页累计解析 {len(records_by_period)} 条记录")
                if len(records_by_period) >= FETCH_TARGET_RECORDS:
                    break
                moved = page.evaluate(
                    """() => {
                        if (typeof goNextPage === 'function') {
                            goNextPage();
                            return true;
                        }
                        const links = Array.from(document.querySelectorAll('a'));
                        const link = links.find(a => /下一页|下页|next/i.test((a.textContent || '').trim()));
                        if (link) {
                            link.click();
                            return true;
                        }
                        return false;
                    }"""
                )
                if not moved:
                    break
                page.wait_for_timeout(1500)
            records = list(records_by_period.values())
            print(f"   成功解析 {len(records)} 条记录")
            browser.close()
    except Exception as e:
        print(f"❌ 抓取失败: {e}")
        import traceback
        traceback.print_exc()
    
    return records


def merge_records(existing_records, new_records):
    """合并数据（增量更新）"""
    existing_periods = {r['period'] for r in existing_records}
    added = 0
    for record in new_records:
        if record['period'] not in existing_periods:
            existing_records.append(record)
            existing_periods.add(record['period'])
            added += 1
    return added


def main():
    print("=" * 60)
    print("🔄 双色球数据更新工具")
    print("=" * 60)
    
    # 加载现有数据
    data = load_existing_data()
    existing_records = data.get('records', [])
    print(f"📁 现有数据: {len(existing_records)} 期")
    
    # 获取新数据
    print("\n📡 正在从500彩票网获取数据...")
    new_records = fetch_from_500()
    
    if new_records:
        print(f"✅ 获取到 {len(new_records)} 条数据")
        
        # 合并数据
        added = merge_records(existing_records, new_records)
        print(f"✅ 新增 {added} 条记录")
        print(f"📊 当前共 {len(existing_records)} 条记录")
        
        # 保存
        save_data(existing_records)
        print(f"\n💾 数据已保存到 {DATA_FILE}")
        print(f"📅 数据范围: {build_date_range(existing_records)}")
    else:
        print("❌ 未能获取新数据")
    
    print("=" * 60)


if __name__ == "__main__":
    main()
