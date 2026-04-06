#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LSTM神经网络预测模块
使用长短期记忆网络学习彩票开奖的时间序列模式
"""

import json
import numpy as np
from collections import Counter
from typing import List, Dict, Tuple
import random

# 尝试导入tensorflow，如果未安装则给出提示
try:
    import tensorflow as tf
    from tensorflow.keras.models import Sequential
    from tensorflow.keras.layers import LSTM, Dense, Dropout
    from tensorflow.keras.optimizers import Adam
    TF_AVAILABLE = True
except ImportError:
    TF_AVAILABLE = False
    print("⚠️ TensorFlow未安装，LSTM预测功能不可用")
    print("   安装命令: pip install tensorflow")


class LSTMPredictor:
    """LSTM神经网络预测器"""
    
    def __init__(self, sequence_length: int = 10):
        self.sequence_length = sequence_length  # 输入序列长度（过去N期）
        self.red_range = 33
        self.blue_range = 16
        self.model = None
        self.is_trained = False
        
    def _encode_draw(self, record: Dict) -> np.ndarray:
        """将一期开奖编码为向量"""
        # 红球：33维one-hot编码
        red_vector = np.zeros(self.red_range)
        for ball in record['red_balls']:
            red_vector[ball - 1] = 1.0
        
        # 蓝球：16维one-hot编码
        blue_vector = np.zeros(self.blue_range)
        blue_vector[record['blue_ball'] - 1] = 1.0
        
        # 合并：49维向量
        return np.concatenate([red_vector, blue_vector])
    
    def _decode_prediction(self, red_probs: np.ndarray, blue_probs: np.ndarray) -> Tuple[List[int], int]:
        """将预测概率解码为号码"""
        # 红球：选择概率最高的6个
        red_indices = np.argsort(red_probs)[-6:][::-1]
        red_balls = sorted([int(i + 1) for i in red_indices])
        
        # 蓝球：选择概率最高的1个
        blue_ball = int(np.argmax(blue_probs)) + 1
        
        return red_balls, blue_ball
    
    def prepare_data(self, records: List[Dict]) -> Tuple[np.ndarray, np.ndarray]:
        """准备训练数据"""
        if len(records) < self.sequence_length + 1:
            raise ValueError(f"数据不足，需要至少{self.sequence_length + 1}期数据")
        
        # 按时间顺序排列（从早到晚）
        timeline = list(reversed(records))
        
        X = []  # 输入序列
        y_red = []  # 红球输出
        y_blue = []  # 蓝球输出
        
        for i in range(len(timeline) - self.sequence_length):
            # 输入：过去sequence_length期
            sequence = [self._encode_draw(timeline[i + j]) for j in range(self.sequence_length)]
            X.append(sequence)
            
            # 输出：下一期
            next_draw = timeline[i + self.sequence_length]
            red_vector = np.zeros(self.red_range)
            for ball in next_draw['red_balls']:
                red_vector[ball - 1] = 1.0
            y_red.append(red_vector)
            
            blue_vector = np.zeros(self.blue_range)
            blue_vector[next_draw['blue_ball'] - 1] = 1.0
            y_blue.append(blue_vector)
        
        return np.array(X), {'red': np.array(y_red), 'blue': np.array(y_blue)}
    
    def build_model(self) -> None:
        """构建LSTM模型"""
        if not TF_AVAILABLE:
            raise RuntimeError("TensorFlow未安装，无法构建模型")
        
        input_shape = (self.sequence_length, self.red_range + self.blue_range)
        
        # 红球预测分支
        red_input = tf.keras.Input(shape=input_shape, name='red_input')
        x = LSTM(64, return_sequences=True)(red_input)
        x = Dropout(0.2)(x)
        x = LSTM(32)(x)
        x = Dropout(0.2)(x)
        red_output = Dense(self.red_range, activation='sigmoid', name='red_output')(x)
        
        # 蓝球预测分支
        y = LSTM(32, return_sequences=True)(red_input)
        y = Dropout(0.2)(y)
        y = LSTM(16)(y)
        y = Dropout(0.2)(y)
        blue_output = Dense(self.blue_range, activation='softmax', name='blue_output')(y)
        
        # 构建模型
        self.model = tf.keras.Model(inputs=red_input, outputs=[red_output, blue_output])
        
        # 编译模型
        self.model.compile(
            optimizer=Adam(learning_rate=0.001),
            loss={'red_output': 'binary_crossentropy', 'blue_output': 'categorical_crossentropy'},
            metrics={'red_output': 'accuracy', 'blue_output': 'accuracy'}
        )
        
        print("✅ LSTM模型构建完成")
        print(f"   输入形状: {input_shape}")
        print(f"   参数数量: {self.model.count_params():,}")
    
    def train(self, records: List[Dict], epochs: int = 50, batch_size: int = 8, validation_split: float = 0.2) -> None:
        """训练模型"""
        if not TF_AVAILABLE:
            raise RuntimeError("TensorFlow未安装，无法训练模型")
        
        if self.model is None:
            self.build_model()
        
        print(f"\n🚀 开始训练LSTM模型...")
        print(f"   序列长度: {self.sequence_length}")
        print(f"   训练轮数: {epochs}")
        print(f"   批次大小: {batch_size}")
        
        # 准备数据
        X, y = self.prepare_data(records)
        print(f"   训练样本数: {len(X)}")
        
        # 训练
        history = self.model.fit(
            X,
            {'red_output': y['red'], 'blue_output': y['blue']},
            epochs=epochs,
            batch_size=batch_size,
            validation_split=validation_split,
            verbose=1
        )
        
        self.is_trained = True
        
        # 显示训练结果
        final_loss = history.history['loss'][-1]
        final_val_loss = history.history['val_loss'][-1]
        print(f"\n✅ 训练完成")
        print(f"   最终训练损失: {final_loss:.4f}")
        print(f"   最终验证损失: {final_val_loss:.4f}")
    
    def predict(self, recent_records: List[Dict]) -> Tuple[List[int], int]:
        """预测下一期"""
        if not TF_AVAILABLE:
            raise RuntimeError("TensorFlow未安装，无法预测")
        
        if not self.is_trained:
            raise RuntimeError("模型未训练，请先调用train()")
        
        if len(recent_records) < self.sequence_length:
            raise ValueError(f"需要至少{self.sequence_length}期历史数据")
        
        # 准备输入序列
        timeline = list(reversed(recent_records))
        sequence = [self._encode_draw(timeline[i]) for i in range(self.sequence_length)]
        X = np.array([sequence])
        
        # 预测
        red_probs, blue_probs = self.model.predict(X, verbose=0)
        
        # 解码预测结果
        red_balls, blue_ball = self._decode_prediction(red_probs[0], blue_probs[0])
        
        return red_balls, blue_ball
    
    def evaluate(self, records: List[Dict]) -> Dict:
        """评估模型性能"""
        if not TF_AVAILABLE:
            raise RuntimeError("TensorFlow未安装，无法评估")
        
        if not self.is_trained:
            raise RuntimeError("模型未训练")
        
        X, y = self.prepare_data(records)
        
        # 预测
        red_probs, blue_probs = self.model.predict(X, verbose=0)
        
        # 计算准确率
        red_correct = 0
        blue_correct = 0
        total_red_overlap = 0
        
        for i in range(len(X)):
            # 解码预测
            pred_red, pred_blue = self._decode_prediction(red_probs[i], blue_probs[i])
            
            # 真实值
            true_red = [j + 1 for j, v in enumerate(y['red'][i]) if v > 0.5]
            true_blue = np.argmax(y['blue'][i]) + 1
            
            # 统计
            red_overlap = len(set(pred_red) & set(true_red))
            total_red_overlap += red_overlap
            
            if pred_blue == true_blue:
                blue_correct += 1
        
        avg_red_overlap = total_red_overlap / len(X)
        blue_accuracy = blue_correct / len(X)
        
        return {
            'avg_red_overlap': avg_red_overlap,
            'blue_accuracy': blue_accuracy,
            'samples': len(X)
        }


def generate_lstm_prediction(records: List[Dict], sequence_length: int = 10) -> Tuple[List[int], int]:
    """使用LSTM生成预测（便捷函数）"""
    if not TF_AVAILABLE:
        print("⚠️ TensorFlow未安装，使用随机预测")
        rng = random.Random()
        return sorted(rng.sample(range(1, 34), 6)), rng.randint(1, 16)
    
    predictor = LSTMPredictor(sequence_length=sequence_length)
    predictor.train(records, epochs=30, batch_size=8)
    return predictor.predict(records)


if __name__ == "__main__":
    # 测试代码
    print("=" * 60)
    print("🧠 LSTM神经网络预测模块")
    print("=" * 60)
    
    if not TF_AVAILABLE:
        print("\n❌ TensorFlow未安装，无法运行测试")
        print("   请执行: pip install tensorflow")
        exit(1)
    
    # 加载数据
    with open('lottery_data.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    records = data['records']
    print(f"\n📊 加载了 {len(records)} 期历史数据")
    
    # 创建预测器
    predictor = LSTMPredictor(sequence_length=10)
    
    # 训练
    predictor.train(records, epochs=30, batch_size=8)
    
    # 评估
    print("\n📈 模型评估:")
    metrics = predictor.evaluate(records)
    print(f"   平均红球重合数: {metrics['avg_red_overlap']:.2f}/6")
    print(f"   蓝球准确率: {metrics['blue_accuracy']*100:.1f}%")
    
    # 预测
    print("\n🎯 LSTM预测结果:")
    for i in range(3):
        red, blue = predictor.predict(records)
        print(f"   第{i+1}注: 红球 {' '.join([f'{b:02d}' for b in red])} + 蓝球 {blue:02d}")
