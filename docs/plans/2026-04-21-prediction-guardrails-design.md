# Prediction Guardrails Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 让预测流程在数据过期时先提示并阻断归档写入，同时避免同一期归档文件被直接覆盖。

**Architecture:** 在 `predict.py` 中新增两个小型保护层。第一层在生成目标期号前校验本地数据日期是否陈旧，若检测到开奖日已过去但本地数据未更新，则输出明确提示并停止预测。第二层在归档写入时保留现有文件，自动生成带时间戳的新归档文件名，避免同一期结果被覆盖。

**Tech Stack:** Python 3, unittest, argparse, datetime, os

---

### Task 1: 为陈旧数据与归档防覆盖写失败测试

**Files:**
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\test_predict.py`
- Test: `c:\Users\wxb\.claude\skills\lottery-predictor-main\test_predict.py`

**Step 1: Write the failing test**

```python
def test_is_data_stale_flags_missing_draw(self):
    ...

def test_save_compact_prediction_keeps_existing_archive(self):
    ...
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest test_predict.PredictFlowTests.test_is_data_stale_flags_missing_draw test_predict.PredictFlowTests.test_save_compact_prediction_keeps_existing_archive -v`
Expected: FAIL because stale-data detection and unique archive naming do not exist yet.

**Step 3: Write minimal implementation**

```python
# do not implement in this task
```

**Step 4: Run test to verify it still fails for the expected reason**

Run: same command as Step 2
Expected: FAIL with missing function or old overwrite behavior.

### Task 2: 实现预测前数据新鲜度保护

**Files:**
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\predict.py`
- Test: `c:\Users\wxb\.claude\skills\lottery-predictor-main\test_predict.py`

**Step 1: Write the failing test**

```python
def test_predict_main_warns_when_data_is_stale(self):
    ...
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest test_predict.PredictFlowTests.test_predict_main_warns_when_data_is_stale -v`
Expected: FAIL because `main()` does not block stale data yet.

**Step 3: Write minimal implementation**

```python
def is_data_stale(...):
    ...
```

**Step 4: Run focused tests**

Run: `python -m unittest test_predict.PredictFlowTests.test_is_data_stale_flags_missing_draw test_predict.PredictFlowTests.test_predict_main_warns_when_data_is_stale -v`
Expected: PASS

### Task 3: 实现归档防覆盖与显示修正

**Files:**
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\predict.py`
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\update_data.py`
- Test: `c:\Users\wxb\.claude\skills\lottery-predictor-main\test_predict.py`

**Step 1: Write the failing test**

```python
def test_save_compact_prediction_keeps_existing_archive(self):
    ...
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest test_predict.PredictFlowTests.test_save_compact_prediction_keeps_existing_archive -v`
Expected: FAIL because the second save reuses the same path.

**Step 3: Write minimal implementation**

```python
def build_archive_output_path(...):
    ...
```

**Step 4: Run focused tests**

Run: `python -m unittest test_predict.PredictFlowTests.test_save_compact_prediction_keeps_existing_archive -v`
Expected: PASS

**Step 5: Fix display-only range output**

Run: `python update_data.py`
Expected: the saved metadata and printed date range are both ordered from older date to newer date.

### Task 4: 重跑预测并验证结果

**Files:**
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\lottery_data.json` (runtime update already happened)
- Modify: `c:\Users\wxb\.claude\skills\lottery-predictor-main\prediction_archive\*.txt` (new runtime archive only)

**Step 1: Run regression tests**

Run: `python -m unittest test_predict.py -v`
Expected: PASS

**Step 2: Run prediction with updated data**

Run: `python predict.py --mode team --num 5`
Expected: output targets `2026044` and writes a non-overwriting archive file.

**Step 3: Verify diagnostics**

Run: IDE diagnostics on edited files
Expected: no new errors
