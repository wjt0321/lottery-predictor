#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
手动数据导入工具
用于将外部获取的数据文件导入到Skill中
"""

import json
import os
import csv
from datetime import datetime
from typing import List, Dict


class ManualDataImporter:
    """手动数据导入器"""
    
    def __init__(self, data_file: str = "lottery_data.json"):
        self.data_file = data_file
        self.data_dir = os.path.dirname(os.path.abspath(__file__))
        self.full_path = os.path.join(self.data_dir, self.data_file)
    
    def import_from_json(self, json_file: str) -> bool:
        """
        从JSON文件导入数据
        
        支持的格式：
        1. 标准格式：[{"period": "2024001", "date": "2024-01-01", "red_balls": [1,2,3,4,5,6], "blue_ball": 7}, ...]
        2. 简单格式：{"2024001": {"date": "2024-01-01", "red": "01,02,03,04,05,06", "blue": "07"}, ...}
        """
        try:
            print(f"正在从 {json_file} 导入数据...")
            
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            records = self._parse_json_data(data)
            
            if records:
                return self._save_records(records, source=f"manual-json-{json_file}")
            else:
                print("❌ 未能解析到有效数据")
                return False
                
        except Exception as e:
            print(f"导入失败: {e}")
            return False
    
    def import_from_csv(self, csv_file: str) -> bool:
        """
        从CSV文件导入数据
        
        支持的列名：
        - 期号/period/issue/code
        - 日期/date/开奖日期/time
        - 红球1-6/red1-6
        - 蓝球/blue
        """
        try:
            print(f"正在从 {csv_file} 导入数据...")
            
            records = []
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                
                for row in reader:
                    record = self._parse_csv_row(row)
                    if record:
                        records.append(record)
            
            if records:
                return self._save_records(records, source=f"manual-csv-{csv_file}")
            else:
                print("❌ 未能解析到有效数据")
                return False
                
        except Exception as e:
            print(f"导入失败: {e}")
            return False
    
    def import_from_text(self, text_file: str) -> bool:
        """
        从文本文件导入数据
        格式：每行一条记录，如：2024001 2024-01-01 01 02 03 04 05 06 07
        """
        try:
            print(f"正在从 {text_file} 导入数据...")
            
            records = []
            with open(text_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    
                    parts = line.split()
                    if len(parts) >= 9:  # 期号 + 日期 + 6个红球 + 1个蓝球
                        try:
                            record = {
                                "period": parts[0],
                                "date": parts[1],
                                "red_balls": sorted([int(x) for x in parts[2:8]]),
                                "blue_ball": int(parts[8])
                            }
                            records.append(record)
                        except:
                            continue
            
            if records:
                return self._save_records(records, source=f"manual-txt-{text_file}")
            else:
                print("❌ 未能解析到有效数据")
                return False
                
        except Exception as e:
            print(f"导入失败: {e}")
            return False
    
    def _parse_json_data(self, data) -> List[Dict]:
        """解析JSON数据"""
        records = []
        
        try:
            # 如果是列表
            if isinstance(data, list):
                for item in data:
                    record = self._parse_json_item(item)
                    if record:
                        records.append(record)
                        
            # 如果是字典
            elif isinstance(data, dict):
                # 尝试不同的键
                for key in ['data', 'records', 'result', 'list']:
                    if key in data and isinstance(data[key], list):
                        for item in data[key]:
                            record = self._parse_json_item(item)
                            if record:
                                records.append(record)
                        break
                
                # 如果上面没找到，尝试直接解析字典的值
                if not records:
                    for period, item in data.items():
                        if isinstance(item, dict):
                            record = self._parse_json_item(item, period)
                            if record:
                                records.append(record)
                                
        except Exception as e:
            print(f"解析JSON数据失败: {e}")
            
        return records
    
    def _parse_json_item(self, item: Dict, default_period: str = "") -> Dict:
        """解析单条JSON记录"""
        try:
            # 期号
            period = str(item.get('period', item.get('issue', item.get('code', default_period))))
            
            # 日期
            date = item.get('date', item.get('time', item.get('openTime', item.get('开奖日期', ''))))
            
            # 红球
            red_balls = []
            if 'red_balls' in item and isinstance(item['red_balls'], list):
                red_balls = sorted([int(x) for x in item['red_balls']])
            elif 'red' in item:
                red_str = str(item['red'])
                red_balls = sorted([int(x.strip()) for x in red_str.split(',')])
            
            # 蓝球
            blue_ball = 0
            if 'blue_ball' in item:
                blue_ball = int(item['blue_ball'])
            elif 'blue' in item:
                blue_ball = int(item['blue'])
            
            # 验证
            if period and date and len(red_balls) == 6 and blue_ball > 0:
                return {
                    "period": period,
                    "date": date,
                    "red_balls": red_balls,
                    "blue_ball": blue_ball
                }
                
        except Exception as e:
            pass
            
        return None
    
    def _parse_csv_row(self, row: Dict) -> Dict:
        """解析CSV行"""
        try:
            # 期号
            period = ""
            for key in ['期号', 'period', 'issue', 'code']:
                if key in row:
                    period = str(row[key])
                    break
            
            # 日期
            date = ""
            for key in ['日期', 'date', '开奖日期', 'time', 'openTime']:
                if key in row:
                    date = row[key]
                    break
            
            # 红球
            red_balls = []
            # 尝试逗号分隔的字符串
            for key in ['红球', 'red', 'redBalls']:
                if key in row and row[key]:
                    red_str = str(row[key])
                    red_balls = sorted([int(x.strip()) for x in red_str.split(',')])
                    break
            
            # 尝试单独列
            if len(red_balls) != 6:
                for i in range(1, 7):
                    for key in [f'红球{i}', f'red{i}', f'red_ball_{i}']:
                        if key in row and row[key]:
                            red_balls.append(int(row[key]))
                            break
                red_balls = sorted(red_balls)
            
            # 蓝球
            blue_ball = 0
            for key in ['蓝球', 'blue', 'blueBall']:
                if key in row and row[key]:
                    blue_ball = int(row[key])
                    break
            
            # 验证
            if period and date and len(red_balls) == 6 and blue_ball > 0:
                return {
                    "period": period,
                    "date": date,
                    "red_balls": red_balls,
                    "blue_ball": blue_ball
                }
                
        except Exception as e:
            pass
            
        return None
    
    def _save_records(self, records: List[Dict], source: str = "manual") -> bool:
        """保存记录"""
        try:
            # 按日期排序（最新的在前）
            records = sorted(records, key=lambda x: x['date'], reverse=True)
            
            data = {
                "metadata": {
                    "total_records": len(records),
                    "date_range": f"{records[-1]['date']} 至 {records[0]['date']}",
                    "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "source": source,
                    "is_real": True
                },
                "records": records
            }
            
            with open(self.full_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            print(f"✅ 成功导入并保存 {len(records)} 条数据")
            print(f"📅 数据范围: {data['metadata']['date_range']}")
            return True
            
        except Exception as e:
            print(f"保存数据失败: {e}")
            return False
    
    def show_import_guide(self):
        """显示导入指南"""
        print("=" * 60)
        print("📖 手动数据导入指南")
        print("=" * 60)
        
        print("\n1️⃣ 从官网下载数据：")
        print("   - 中国福利彩票官网: http://www.cwl.gov.cn/")
        print("   - 500彩票网: https://datachart.500.com/ssq/")
        print("   - 下载Excel或CSV格式的历史数据")
        
        print("\n2️⃣ 支持的文件格式：")
        print("   - JSON: 标准JSON数组格式")
        print("   - CSV: 包含期号、日期、红球、蓝球列")
        print("   - TXT: 每行一条记录，空格分隔")
        
        print("\n3️⃣ 使用方法：")
        print("   python manual_data_import.py --json data.json")
        print("   python manual_data_import.py --csv data.csv")
        print("   python manual_data_import.py --txt data.txt")
        
        print("\n4️⃣ 数据格式示例：")
        print("   JSON: [{\"period\":\"2024001\",\"date\":\"2024-01-01\",")
        print("          \"red_balls\":[1,2,3,4,5,6],\"blue_ball\":7}]")
        print("   CSV: 期号,日期,红球1,红球2,红球3,红球4,红球5,红球6,蓝球")
        print("   TXT: 2024001 2024-01-01 01 02 03 04 05 06 07")


def main():
    """主函数"""
    import sys
    
    importer = ManualDataImporter()
    
    if len(sys.argv) < 2:
        importer.show_import_guide()
        return
    
    file_path = sys.argv[-1]
    
    if not os.path.exists(file_path):
        print(f"❌ 文件不存在: {file_path}")
        return
    
    success = False
    
    if '--json' in sys.argv:
        success = importer.import_from_json(file_path)
    elif '--csv' in sys.argv:
        success = importer.import_from_csv(file_path)
    elif '--txt' in sys.argv:
        success = importer.import_from_text(file_path)
    else:
        # 根据扩展名自动判断
        ext = os.path.splitext(file_path)[1].lower()
        if ext == '.json':
            success = importer.import_from_json(file_path)
        elif ext == '.csv':
            success = importer.import_from_csv(file_path)
        elif ext == '.txt':
            success = importer.import_from_text(file_path)
        else:
            print("❌ 不支持的文件格式，请使用 --json, --csv 或 --txt 指定")
            return
    
    if success:
        print("\n✅ 数据导入成功！")
    else:
        print("\n❌ 数据导入失败")


if __name__ == "__main__":
    main()
