# 马里文共和国 · Mariven Republic

> 一个全维度、数据驱动的活性国家模型（Living Nation Model）。
> 虚拟发展中国家，南太平洋，真实数据驱动，每天自己更新自己。

---

## 概述

马里文共和国是一个**虚构但完全真实的模拟国家**。它不是游戏——没有玩家目标。它不是一个实验——没有假设要验证。它是一个**每天自己运转的活性模型**：天气在变、汇率在波动、CPI每月15日发布、气旋季有真实历史数据可查。

**坐标**：20°47'41.8"S, 176°26'05.4"E（南太平洋，斐济以东约400km）
**人口**：120万 | **面积**：14,820 km² | **四岛**：马卡迪·蒂莫·佩拉·鲁瓦
**独立**：1970年从英国独立 | **现行宪法**：1992年（2013年修订）
**GDP**：$75亿 USD | **人均**：$6,250 | **时区**：UTC+12

---

## 项目结构

```
mariven-republic/
├── README.md
│
├── gov.mv/                    # 政府门户网站
│   └── index.html             # 中英双语，75项数据面板
├── meteo.gov.mv/              # 气象局网站
│   └── index.html             # 天气/海洋/火山/UV
├── airmariven.mv/             # 国家航空网站
│   └── index.html             # 航班/预订/行李
│
└── sim-engine/                # 模拟引擎
    ├── engine/                # 核心模型
    │   ├── weather_model.py   # 天气 (Markov + 真实SOI + 正弦温度)
    │   ├── exchange_model.py  # 汇率 (FRED真实数据 + 五币篮子)
    │   ├── commodities_model.py # 商品 (世界银行Pink Sheet)
    │   ├── inflation_model.py # CPI通胀 (加权篮子 + 发布日逻辑)
    │   ├── engine.py          # 每日Tick主循环
    │   ├── archive.py         # JSON快照 + SQLite存档
    │   └── retrieve.py        # 历史检索 + 世界文档搜索
    │
    ├── data/                  # 真实数据源
    │   ├── soi_monthly.csv    # NOAA南方涛动指数 (1991-2026)
    │   ├── aud_usd.csv        # FRED 澳元汇率 (1971-2026)
    │   ├── nzd_usd.csv        # FRED 新西兰元汇率
    │   ├── eur_usd.csv        # FRED 欧元汇率
    │   ├── usd_cny.csv        # FRED 人民币汇率
    │   ├── commodities_real.csv # 世界银行商品价格 (1960-2024)
    │   ├── cyclones_mariven.json # IBTrACS 南太平洋气旋 (24次近距)
    │   └── nation_profile.json   # 国家静态设定
    │
    ├── worldbuilding/         # 世界构建文档 (84份)
    │   ├── constitution.md    # 宪法 (96条, 英文)
    │   ├── constitution-zh.md # 宪法 (中文翻译)
    │   ├── geography-anchor.md # 地理锚点
    │   ├── 03-history.md      # 简史
    │   ├── 03d-post-independence-history.md # 独立后详细史
    │   ├── 04-demographics.md # 人口与宗教
    │   ├── 05-politics.md     # 政治体系
    │   ├── 09-economy.md      # 经济结构
    │   ├── ... (74份更多文档)
    │   └── misc-data.md       # 各类统计数据
    │
    ├── docs/
    │   └── model-catalog.md   # 75子系统模型全量目录
    │
    ├── widgets/
    │   └── weather-widget.html # 天气组件
    │
    └── dashboard.html         # 国家运营中心 (25面板)
```

---

## 数据模型（P0 — 4/8 完成）

P0 已实现范围（天气、汇率、商品价格和 CPI）均通过每日主 Tick 运行；下表其余四项仍为规划模型。CPI 只在每月 15 日发布新的官方值，其他日期保持最近一次发布值。商品数据输出同时包含 `source_month`、`staleness_days` 和 `is_stale`，调用方可以明确识别回填数据的新鲜度。

| # | 模型 | 状态 | 数据源 | 说明 |
|---|------|------|--------|------|
| 1 | **天气** | ✅ | 真实SOI (NOAA) | Markov链 + 正弦温度 + Gamma降雨。五城每日输出。ENSO驱动。 |
| 2 | **汇率** | ✅ | 真实FRED数据 | 五币篮子(AUD/NZD/USD/CNY/EUR)加权。央行干预。OU过程。 |
| 3 | **商品价格** | ✅ | 世界银行Pink Sheet | 糖/金/布伦特原油。1960-2024真实月度数据。 |
| 4 | **CPI通胀** | ✅ | 上游模型联动 | 食品35%+燃料18%+住房15%+交通12%+其他20%。每月15日发布。 |
| 5 | GDP | ⬜ | — | 季度发布，商品价格+旅游+天气冲击 |
| 6 | 人口 | ⬜ | — | 出生率-死亡率+净移民差分方程 |
| 7 | 登革热 | ⬜ | — | 季节性SIR + Wolbachia阻断 |
| 8 | 犯罪 | ⬜ | — | 失业率回归 + 泊松抽样 |

完整75个子系统模型目录：[model-catalog.md](sim-engine/docs/model-catalog.md)

---

## 数据来源（全部公开免费）

| 数据 | 来源 | 频率 | 覆盖 |
|------|------|------|------|
| **SOI** | NOAA / Queensland Government | 月度 | 1991-2026 |
| **气旋轨迹** | IBTrACS v4 (NOAA) | 6小时 | 1968-2024 (南太平洋) |
| **汇率** | FRED (美联储经济数据库) | 月度 | 1971-2026 |
| **商品价格** | World Bank Pink Sheet | 月度 | 1960-2024 |
| **外汇** | FRED | 月度 | AUD/NZD/EUR 1971-, CNY 1981- |

---

## 快速开始

### 1. 运行主 Tick

```bash
cd sim-engine
python engine/engine.py --days 1
python engine/engine.py --days 30
python engine/engine.py --days 365 --dry-run
```

`--days` 指定连续执行的每日 Tick 数。`--dry-run` 会把每个 Tick 的逐日摘要打印到标准输出，但绝不写入 `data/state.json`、JSON 历史归档或 SQLite 事件库；适合年度校准和验证。

### 2. 运行测试

```bash
python -m unittest discover -s tests -p "test*.py" -v
```

### 3. 查看国家运营中心

浏览器打开 `sim-engine/dashboard.html` — 75张数据卡片 + 实时状态。

### 4. 浏览网站

- `gov.mv/index.html` — 政府门户
- `meteo.gov.mv/index.html` — 气象局
- `airmariven.mv/index.html` — 航空

---

## 设计理念

**"活性国家模型"（Living Nation Model）**

- **全维度**：75个子系统——从天气到汇率、从登革热到议会支持率
- **真实数据驱动**：天气由真实SOI驱动，汇率锚定FRED，商品价格来自世界银行
- **每日运转**：主 Tick 推进一天，并按固定顺序更新已实现的 P0 天气、汇率、商品和 CPI 模型
- **多站产出**：同一事件驱动多个网站的不同内容——气象局、时报、政府门户、航空公司
- **中英双语**：政府网站支持完整语言切换

---

## 贡献

欢迎提交 Issue 和 Pull Request。特别需要的帮助：

- [ ] P0剩余模型 (GDP, 人口, 登革热, 犯罪)
- [ ] P1模型 (海洋, 旅游, 产业, 火山)
- [ ] IBTrACS气旋实时接入
- [ ] 每日新闻自动生成管道
- [ ] 移动端响应式优化

---

## 许可

MIT License © 2026

---

*"本宪法诞生于一场战争的灰烬之中——那场战争夺走了十五万八千人的生命。本文件中的每一个字——都是一块石头——压在他们的坟上——不是要加重——是要建一座他们终于可以在里面安息的房子。"*
— 1992年《马里文共和国宪法》序言
