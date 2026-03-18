# 基础过滤层设计

## 定位

声明式量化筛选引擎。通过 YAML 配置定义排除规则、过滤条件、评分因子和分级标准，从全市场 ~5500 只股票中筛选出符合特定投资哲学的候选标的。

核心特点：**零代码筛选** — 所有筛选逻辑均在 strategy.yaml 中声明，引擎代码完全策略无关。

## 筛选流水线

```
全市场 DataFrame (~5500 只)
    │
    ▼ Step 1: 排除规则 (_apply_excludes)
    │   - 字段包含指定关键词的股票被排除
    │   - 如: name contains ["ST", "退"]
    │
    ▼ Step 2: 预计算因子合并
    │   2a. 截面因子 (api.get_factors → 按 ts_code+trade_date 合并)
    │   2b. 时序因子 (api.get_ts_factors → 按 ts_code 合并)
    │   2c. 因子缺失时 fallback 到 FactorRegistry 即时计算
    │
    ▼ Step 3: 声明式过滤 (_apply_filters)
    │   - 每个 filter 定义 field + min/max 边界
    │   - 支持 fallback 字段链
    │   - 越界即淘汰
    │
    ▼ Step 4: 加权评分 (_compute_scores)
    │   - 每个 scoring factor 定义 field + weight + full/zero 值
    │   - 线性归一化到 0-100
    │   - 加权求和得到 tier_score
    │
    ▼ Step 5: 评级分级 (_compute_tiers)
    │   - 多条件 AND 匹配（如 PE≤8 且 PB≤0.8 且 DV≥7.0）
    │   - 从高到低匹配，首次命中即确定等级
    │
    ▼ Step 6: 排序 + Top N
    │   - 按 tier_score 降序
    │
    ▼ 输出: ScreenResult
```

## YAML 配置结构

以 `strategies/v6_value/strategy.yaml` 的 `screening` 部分为例：

```yaml
screening:
  # 1. 排除规则：字段包含关键词即排除
  exclude:
  - field: name
    contains: [ST, 退]

  # 2. 过滤条件：min/max 边界
  filters:
  - field: pe_ttm
    min: 0.01
    max: 15.0
  - field: pb
    min: 0.01
  - field: total_mv
    min: 1000000.0        # 万元（原始单位）
  - field: dv
    min: 0.01

  # 3. 评分因子
  scoring:
    factors:
    - field: pe_ttm
      weight: 0.3
      lower_better: true      # PE 越低越好
      full: 6.0               # 满分值：PE=6 → 100分
      zero: 15.0              # 零分值：PE=15 → 0分
    - field: pb
      weight: 0.3
      lower_better: true
      full: 0.5
      zero: 1.5
    - field: dv
      weight: 0.4
      lower_better: false     # 股息率越高越好
      full: 8.0
      zero: 2.0

    # 4. 分级条件（从高到低依次匹配，名称由策略自定义）
    # 示例为 v6_value 策略，v6_enhanced 使用 S级/A级/B级
    tiers:
    - name: 金龟
      conditions:
      - {field: pe_ttm, max: 8.0}
      - {field: pb, max: 0.8}
      - {field: dv, min: 7.0}
    - name: 银龟
      conditions:
      - {field: pe_ttm, max: 10.0}
      - {field: pb, max: 1.0}
      - {field: dv, min: 5.0}
    - name: 铜龟
      conditions:
      - {field: pe_ttm, max: 12.0}
      - {field: pb, max: 1.2}
      - {field: dv, min: 4.0}
    default_tier: 不达标
```

## 评分算法

### 线性归一化

每个 scoring factor 独立计算 0-100 分：

```
lower_better=true (如 PE):
  score = (zero_val - actual) / (zero_val - full_val) × 100
  例: PE=8, zero=15, full=6 → (15-8)/(15-6)×100 = 77.8分

lower_better=false (如 DV):
  score = (actual - zero_val) / (full_val - zero_val) × 100
  例: DV=7%, zero=2, full=8 → (7-2)/(8-2)×100 = 83.3分

所有分数 clamp 到 [0, 100]
```

### 加权合成

```
tier_score = Σ(factor_score_i × weight_i) / Σ(weight_i)
```

### 分级匹配

```python
for tier in tiers:  # 从金龟到铜龟
    if all(condition.matches(row) for condition in tier.conditions):
        return tier.name
return default_tier  # 不达标
```

## 字段解析与 Fallback

`_resolve_field()` 实现了灵活的字段解析：

```
定义: field=dv, fallback=dv_ttm,dv_ratio

解析链:
1. 尝试 df['dv']         ← 预计算因子（优先）
2. 尝试 df['dv_ttm']     ← 原始指标
3. 尝试 df['dv_ratio']   ← 备选字段
4. 返回 NaN              ← 全部缺失
```

这使得筛选配置不需要关心数据来自预计算因子还是原始指标——只需声明字段名，引擎自动解析。

## 因子合并策略

### 截面因子

```python
# 从 factor_store 读取预计算值
factors_df = api.get_factors(cutoff_date, cutoff_date)
if not factors_df.empty:
    df = df.merge(factors_df[['ts_code'] + new_cols], on='ts_code', how='left')
```

### 时序因子

```python
# 时序因子是静态属性（每股票一行），直接按 ts_code 合并
ts_factors_df = api.get_ts_factors()
if not ts_factors_df.empty:
    df = df.merge(ts_factors_df[['ts_code'] + new_cols], on='ts_code', how='left')
```

### Fallback 计算

当预计算因子不存在时（如首次运行），回退到即时计算：

```python
if factor_cols_missing:
    registry = FactorRegistry(strategy_dir)
    df = registry.compute_all(df)  # 即时计算所有截面因子
```

## 输出格式

### ScreenResult 数据结构

```python
@dataclass
class ScreenResult:
    cutoff_date: str
    trade_date: str              # 实际截面交易日（<= cutoff_date 的最近交易日）
    total_stocks: int            # 全市场股票数
    after_basic_filter: int      # 基础过滤后
    candidates: pd.DataFrame     # Top N 候选（含 tier_score, tier_rating 列）
```

### Markdown 输出

```markdown
# 量化筛选结果: 2024-06-30

- 全市场股票数: 5338
- 基础过滤后: 326
- 候选数: 50

## 评级分布
- 金龟: 8 只
- 银龟: 29 只
- 铜龟: 5 只
- 不达标: 8 只
```

## 调用方式

```bash
# 通过 Launcher（推荐）
python -m src.engine.launcher strategies/v6_value/strategy.yaml screen 2024-06-30
python -m src.engine.launcher strategies/v6_value/strategy.yaml screen 2024-06-30 --top 100

# 直接模块调用
python -m src.screener.quick_filter 2024-06-30
```

## 设计约束

1. **无副作用**：筛选过程只读数据，不修改任何状态
2. **可重复性**：相同 cutoff_date + strategy.yaml → 相同结果
3. **策略无关**：引擎不包含"PE 低于多少算便宜"的假设，全部由 YAML 声明
4. **StrategyConfig 驱动**：筛选参数通过 `StrategyConfig` 加载，无 fallback 默认值
