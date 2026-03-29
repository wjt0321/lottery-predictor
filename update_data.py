#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据更新脚本
从500彩票网获取最新双色球开奖数据并增量更新
"""

import json
import os
from datetime import datetime
from playwright.sync_api import sync_playwright


DATA_FILE = "lottery_data.json"


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
            "date_range": f"{records[-1]['date']} 至 {records[0]['date']}",
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
    records = []
    
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
            rows = page.query_selector_all('#tdata tr')
            
            for i, row in enumerate(rows):
                try:
                    cells = row.query_selector_all('td')
                    if len(cells) >= 16:  # 实际有16个单元格
                        period = cells[0].inner_text().strip()
                        red_balls = []
                        for j in range(1, 7):
                            ball_text = cells[j].inner_text().strip()
                            if ball_text.isdigit():
                                red_balls.append(int(ball_text))
                        
                        blue_text = cells[7].inner_text().strip()
                        blue_ball = int(blue_text) if blue_text.isdigit() else 0
                        # 日期在第15列（索引15），但先检查是否存在
                        date_text = cells[15].inner_text().strip() if len(cells) > 15 else ''
                        
                        # 调试输出前3行
                        if i < 3:
                            print(f"   第{i+1}行: 期号={period}, 红球数={len(red_balls)}, 蓝球={blue_ball}, 日期={date_text}")
                        
                        if period and len(red_balls) == 6 and blue_ball > 0 and date_text:
                            records.append({
                                "period": f"20{period}",
                                "date": date_text,
                                "red_balls": sorted(red_balls),
                                "blue_ball": blue_ball
                            })
                except Exception as e:
                    if i < 3:
                        print(f"   第{i+1}行解析错误: {e}")
                    continue
            
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
        print(f"📅 数据范围: {existing_records[-1]['date']} 至 {existing_records[0]['date']}")
    else:
        print("❌ 未能获取新数据")
    
    print("=" * 60)


if __name__ == "__main__":
    main()
