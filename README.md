# 马里文共和国 · Mariven Republic

> 一个以真实公开数据为锚点、按日确定性运行的虚构国家模型。
> A deterministic living-nation simulation anchored in real public data.

马里文共和国是一个虚构的南太平洋发展中国家。本仓库把世界观资料、公开数据、确定性模拟模型和多个国家网站放在同一套可追溯体系中：天气、汇率、商品价格、CPI 与人口会在每日 Tick 中依次更新，相同状态与种子始终产生相同结果。

> [!IMPORTANT]
> 马里文、其政府、机构、人物与事件均为虚构内容。现实数据仅用于模型校准和方法参考。

## English summary

Mariven Republic is a fictional South Pacific country implemented as a reproducible living-nation model. The repository combines 84 worldbuilding documents, public datasets, government-facing web prototypes, and a deterministic Python simulation engine. Five P0 models currently run in the daily pipeline: weather, foreign exchange, commodity prices, CPI inflation, and a full single-age population cohort model.

## 国家快照

| 项目 | 设定 |
|---|---|
| 坐标 | 20°47′41.8″S, 176°26′05.4″E，斐济以东约 400 km |
| 国土面积 | 14,820 km² |
| 基准人口 | 1,200,000（2026-08-11） |
| 主要岛屿 | 马卡迪、蒂莫、佩拉、鲁瓦 |
| 独立 | 1970 年脱离英国独立 |
| 宪法 | 1992 年宪法，2013 年修订 |
| 时区 | UTC+12 |
| 货币 | 马里文元（MVL） |

## 当前可运行模型

P0 已完成 5/8。五个已实现模型均由 [`sim-engine/engine/engine.py`](sim-engine/engine/engine.py) 的每日主循环统一编排。

| 模型 | 状态 | 核心方法 | 主要输出 |
|---|:---:|---|---|
| 天气 | ✅ | Markov 状态、南半球季节曲线、Gamma 降雨、SOI/ENSO | 五城天气、降雨、海温与风险事件 |
| 汇率 | ✅ | 五币篮子、均值回归、确定性随机冲击 | MVL/USD 与交叉汇率 |
| 商品价格 | ✅ | 世界银行月度数据、确定性回填 | 糖、黄金、布伦特原油与数据新鲜度 |
| CPI 通胀 | ✅ | 分类权重、燃油传导、月度发布日 | CPI 指数、同比、环比和分类贡献 |
| 人口 | ✅ | 单岁年龄×性别队列、生命表、出生与迁移账本 | 总人口、年龄结构、抚养比与每日人口流量 |
| GDP | ⬜ | 规划中 | 季度 GDP 与增长贡献 |
| 登革热 | ⬜ | 规划中 | 周病例、传播状态与医疗压力 |
| 犯罪 | ⬜ | 规划中 | 分类案件、风险与事件 |

完整子系统路线图见 [`sim-engine/docs/model-catalog.md`](sim-engine/docs/model-catalog.md)。

## 完整年龄队列人口模型

人口模型使用 schema v3 状态，是当前模拟引擎中最完整的结构模型：

- 内部维护男性、女性各 0–100+ 岁，共 202 个单岁队列。
- 每个年龄—性别队列再分为 12 个生日月份桶，月初按桶推进年龄。
- 统一结算出生、基线全因死亡、显著/超额死亡、侨民回流、外国移民与永久移出。
- 显著事故死亡由事件模型分类，但人口只在统一账本中扣除一次。
- 第一滚动 365 天在无超额死亡情景下精确执行：出生 27,500、基线死亡 6,600、回流 2,500、外国移民 2,200、移出 2,800，期末人口 1,222,800。
- 第一周期后，出生按年龄别生育暴露与 TFR 路径演化；死亡按年龄结构与生命表演化；迁移参数按版本化周期状态持久化。
- 2026 基线的中位年龄、生命表和年度死亡量经过联合校准，内部队列、公开人口对象与顶层总人口必须始终一致。

基线设计说明见 [`docs/superpowers/specs/2026-07-16-complete-age-cohort-population-model-design.md`](docs/superpowers/specs/2026-07-16-complete-age-cohort-population-model-design.md)。

## 每日数据流

```mermaid
flowchart LR
    A["加载并迁移状态"] --> B["天气"]
    B --> C["汇率"]
    C --> D["商品价格"]
    D --> E["CPI"]
    E --> F["显著事件与死亡分类"]
    F --> G["人口队列结算"]
    G --> H["schema v3 完整验证"]
    H --> I["JSON 快照与 SQLite 索引"]
```

各模型使用隔离的命名随机流。人口模型升级到 schema v3 后，天气、汇率、商品、CPI 和既有事件仍保留原有 schema v2 随机序列，避免模型新增导致历史结果漂移。

## 快速开始

### 环境

- Python 3
- 运行时只使用 Python 标准库
- Tick 运行时无需联网

### 运行每日模拟

```bash
cd sim-engine

# 推进 1 天并写入状态、JSON 归档和 SQLite
python engine/engine.py --days 1

# 连续推进 30 天
python engine/engine.py --days 30

# 只运行和打印 365 天，不修改任何运行文件
python engine/engine.py --days 365 --dry-run
```

`--dry-run` 不会修改：

- `sim-engine/data/state.json`
- `sim-engine/output/events.db`
- `sim-engine/output/archive/`

### 运行测试

```bash
cd sim-engine
python -m unittest discover -s tests -p "test*.py" -v
```

当前测试覆盖确定性、随机流隔离、schema v1/v2→v3 迁移、严格 JSON、断点恢复、死亡去重、年龄推进、365 天精确账本、2035 长期演化，以及 dry-run 不落盘。

### 查看七天诊断报告

```bash
cd sim-engine
python test_7days.py
```

## 数据来源与可追溯性

| 数据 | 权威来源 | 用途 |
|---|---|---|
| SOI / ENSO | NOAA、Queensland Government | 天气状态与降雨季节性 |
| 气旋轨迹 | NOAA IBTrACS v4 | 南太平洋历史气旋锚点 |
| 外汇 | Federal Reserve Economic Data（FRED） | AUD、NZD、EUR、CNY 等汇率篮子 |
| 商品价格 | World Bank Pink Sheet | 糖、黄金和布伦特原油 |
| 单岁人口先验 | UN World Population Prospects 2024 | Fiji 2026 中方案、0–100+、分性别结构 |
| 人口普查交叉核对 | Fiji Bureau of Statistics | 2017 年年龄—性别人口结构 |

人口源数据链可复现：

1. [`sim-engine/scripts/extract_wpp_fiji_2026.py`](sim-engine/scripts/extract_wpp_fiji_2026.py) 从联合国官方压缩 CSV 提取 Fiji 2026 的 101 个单岁年龄。
2. [`sim-engine/data/sources/wpp2024_fiji_2026_single_age_sex.json`](sim-engine/data/sources/wpp2024_fiji_2026_single_age_sex.json) 保存小型源摘录、官方 URL、版本、访问日期、许可和源文件/数组 SHA-256。
3. [`sim-engine/scripts/build_population_baseline.py`](sim-engine/scripts/build_population_baseline.py) 将先验校准为马里文 1,200,000 人基线。
4. [`sim-engine/data/population_baseline_2026.json`](sim-engine/data/population_baseline_2026.json) 是 Tick 直接读取的已提交运行产物。

联合国 WPP 数据按 CC BY 3.0 IGO 标注；其他外部数据的再利用应遵循各自来源条款。

## 仓库结构

```text
mariven-republic/
├── README.md
├── docs/
│   └── superpowers/specs/       # 已确认的模型设计规格
├── gov.mv/                      # 政府门户原型
├── meteo.gov.mv/                # 气象局网站原型
├── airmariven.mv/               # 国家航空网站原型
└── sim-engine/
    ├── engine/                  # 每日 Tick、状态、模型、归档和检索
    ├── data/                    # 运行状态、校准数据和源数据摘录
    ├── scripts/                 # 可复现数据构建脚本
    ├── tests/                   # unittest 测试套件
    ├── worldbuilding/           # 84 份国家设定与制度文档
    ├── docs/model-catalog.md    # 全量子系统目录
    ├── dashboard.html           # 国家运营中心原型
    └── test_7days.py            # 七天只读诊断报告
```

## 主要入口

- [模拟引擎](sim-engine/engine/engine.py)
- [人口模型](sim-engine/engine/population_model.py)
- [模型目录](sim-engine/docs/model-catalog.md)
- [人口与宗教设定](sim-engine/worldbuilding/04-demographics.md)
- [政府门户](gov.mv/index.html)
- [气象局](meteo.gov.mv/index.html)
- [马里文航空](airmariven.mv/index.html)
- [国家运营中心](sim-engine/dashboard.html)

## 设计原则

- **确定性优先**：相同状态、日期、schema 与命名随机流产生相同结果。
- **单一账本**：人口、死亡和流量只由一个权威模型结算，避免重复计算。
- **真实数据只作锚点**：现实数据提供形状、范围和方法，不把 Fiji 直接复制成马里文。
- **运行时离线**：外部数据先提取、校验并提交，日常 Tick 不访问网络。
- **状态可迁移**：旧 schema 显式迁移，新 schema 严格拒绝损坏状态。
- **模型隔离**：新增模型不得改变已有模型的随机结果。
- **世界观可追溯**：关键数字同时落在设定文档、源数据、生成脚本和测试中。

## 路线图

- [x] 天气
- [x] 汇率
- [x] 商品价格
- [x] CPI 通胀
- [x] 完整年龄队列人口模型
- [ ] GDP
- [ ] 登革热
- [ ] 犯罪
- [ ] 海洋、旅游、产业与灾害等 P1 模型
- [ ] 网站与模拟状态的自动发布管道

## 参与项目

欢迎通过 Issue 或 Pull Request 提交：

- 模型校准与测试改进
- 可核验的公开数据源
- 世界观内部一致性修订
- 政府、气象、航空与运营中心界面
- 中英文文档改进

提交模型改动时，请同时说明数据来源、状态迁移影响、随机流兼容性和验证方法。

## 许可说明

本仓库目前尚未单独提交项目级 `LICENSE` 文件。外部数据、资料与摘录仍受其原始来源条款约束；引用或再利用前请核对对应数据文件中的来源和许可信息。

---

> “本宪法诞生于一场战争的灰烬之中……不是要加重，是要建一座他们终于可以在里面安息的房子。”
> — 1992 年《马里文共和国宪法》序言（虚构）
