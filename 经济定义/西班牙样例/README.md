# 西班牙 OECD FUA 地理围栏样例（待审核）

构建日期：2026-11-01。沿用德国样例的路线，以 OECD 市镇成员表建立城市功能区（FUA）的候选边界，使用 GISCO 官方市镇编码连接，不使用模糊地名匹配。

**本样例完成成员连接、边界拼合和技术验证，尚未确认与实际 OECD 经济指标使用的地理口径完全一致。** 本次没有下载或清洗新的西班牙 GDP 等经济观测，也未接入产品地图。

## 结果

| 项目 | 结果 |
|---|---:|
| OECD 西班牙 FUA | 81 |
| OECD 原始成员记录 | 1,264 |
| 直接编码匹配 | 1,262 / 1,264（99.84%） |
| 不能对应市镇底图的特殊单元 | 2 |
| 成员齐全的 FUA（按编码） | 80 |
| 成员不齐的 FUA | 1：Melilla（ES045F） |
| 有效、非空的候选 FUA 面 | 81 |
| GISCO 2024 西班牙 LAU 底图单元 | 8,132 |
| 同码名称写法差异 | 109 |
| 可取得的同码官方 FUA 参考 | 66 |
| 在所用官方索引中没有同码参考 | 15 |

81 个 FUA 指这份 OECD 快照中的区域，不代表西班牙全部市镇均位于 FUA，也不是全国无缝覆盖行政地图。80 个“成员齐全”只表示成员名单的编码均有对应几何，不能视为地理定义或历史边界已获人工验收。

## 先看哪些文件

- `outputs/02_成员编码匹配.csv`：全部成员、5 位编码、GISCO 编码、名称差异和状态。
- `outputs/03_未匹配与特殊单元.csv`：两条缺口及官方背景依据。
- `outputs/06_西班牙FUA覆盖汇总.csv`：81 个区域的覆盖、面积与审核状态。
- `outputs/07_西班牙FUA候选边界.geojson` 与同名 `.gpkg`：QGIS 可打开的候选边界。
- `outputs/08_与GISCO官方FUA空间比较.csv`：66 个同码参考的名称、面积、交并比及差异。
- `outputs/09_需复核的FUA.csv`、`11_市镇层面参考边界差异.csv`：逐区域和逐市镇定位问题。
- `outputs/12_马德里与巴塞罗那边界对照.png`：两个主要城市的拼合与参考范围对照。
- `outputs/verification.json` 和 `quality_summary.json`：技术验证及机器可读汇总。

## 来源、编码和时间

为与已提交的德国样例保持可比，本次复用 2026-10-14 获取的 OECD 原始成员表快照和 2026-10-15 获取的 GISCO LAU 2024 快照，不宣称它们是 2026-11-01 的最新定义。西班牙 FUA 参考几何于本次构建时从 GISCO 官方地址获取，选取文件名包含 2024 的版本。参考单位索引同样固定为德国样例使用的 2024 索引快照。各来源的 URL、实际获取时间、字节数和 SHA256 在 `sources.json`；缺少参考的 15 个代码在 `reference_manifest.json` 保留明确状态。

INE 官方说明，市镇码为 5 位：前两位为省码，后三位为省内市镇码。本次将 OECD `pk` 的 `ESP` 前缀去掉，并与 GISCO `GISCO_ID` 去掉 `ES_` 后的 5 位字符串比较，例如 `ESP28079` 对应 `ES_28079`。不转成整数，不丢前导零，不把同名当作同一市镇。[INE 编码说明](https://www.ine.es/daco/daco42/codmun/codmun00i.htm)

编码唯一性与成员归属被校验；跨 FUA 的重复成员清单也单独输出。名称差异保留原样，包括冠词位置、重音、不同语言写法等，仅作人工复核提示，不用于自动改写归属。

## 两个无法匹配的特殊单元

| OECD 成员编码 | 原名称 | OECD 列入的 FUA | 本次处理 |
|---|---|---|---|
| ESP54003 | Islas Chafarinas | ES045F Melilla | 无同码 LAU，保留 unresolved_code |
| ESP54005 | Peñón de Alhucemas | ES045F Melilla | 无同码 LAU，保留 unresolved_code |

这两条是 OECD 原表的成员记录，不能据此认定它们属于 Melilla 市镇的行政辖区。IGN 的行政区划说明将相关单元列为不属于市镇划分的特殊地域；这一背景与本次市镇底图无同码要素的现象相符，但本次没有取得它们的独立几何进行补齐。[IGN 官方说明](https://educativo.ign.es/atlas-didactico/organizacion-territorial-bach/estructuracin_interna.html)

Melilla FUA 共 3 条成员，只有 `ESP52001` 成功匹配，因此候选面仅含这一市镇，`members_unresolved=2`、`coverage_status=partial`、`area_is_partial=true`。不将另外两条重复赋给 Melilla 面，不补点、不画缓冲区，也不把缺失面积记为零。地名与归属记录按来源保留，不对领土主张作额外判断。

## 参考边界存在显著差异

| FUA | OECD 成员覆盖 | 与同码 GISCO 2024 参考的 IoU |
|---|---:|---:|
| Madrid（ES001F） | 166 / 166 | 68.45% |
| Barcelona（ES002F） | 135 / 135 | 61.35% |
| Valencia（ES003F） | 63 / 63 | 30.32% |
| Santa Cruz de Tenerife（ES024F） | 13 / 13 | 40.62% |
| Melilla（ES045F） | 1 / 3，部分覆盖 | 88.53% |

IoU 为交集面积除以并集面积。66 个参考比较的中位数约为 65.66%；7 个达到 98% 诊断阈值，58 个低于阈值，另有 1 个 Melilla 因成员缺失被优先标为 partial。15 个没有参考的区域保留空值，不填 0。

98% 仅用于排序复核，不是验收标准。同码、同名或高编码覆盖均不证明两套范围等价。市镇层为 01M、参考 FUA 为 100K，概化尺度也不同；本次尚未逐项区分成员定义、年份与几何概化的影响，不会把面积差全部归于概化误差。候选边界始终按 OECD 原成员表拼合，不为贴近参考而自动增删成员。参考几何来自另行发布的 FUA 文件，但与市镇底图同属 GISCO，不构成完全独立的测绘验证。

INE 在当前方法说明的第 19 页记载，自 2025 版起，部分 FUA 随基于 2021 年人口普查的类型更新而调整，跨版指标差异可能由范围改变产生。这进一步说明版本核对应先于经济分析；**这条说明不能证明本次所有差异都由该轮更新造成**。[INE 方法说明，第 19 页](https://www.ine.es/metodologia/iu/metodologia_IU.pdf)

继续科研使用前，应核实实际选用 OECD GDP/其他指标的数据集、FUA 定义版本和适用年份，并用相同版本的成员表或原生边界核对。2024 底图不能自动当作历史年份或最新版本经济指标的边界。本次未完成 OECD 原生 FUA 几何的独立核对；候选面与 GISCO 参考范围不能直接互换。

## 文件字段与几何

| 字段 | 含义 |
|---|---|
| `pk`、`member_ine5` | OECD 原始标识、用于连接的 5 位编码，按文本保存 |
| `fuacode` / `fua_code` | OECD FUA 编码；不能跨来源假定同码范围一致 |
| `gisco_id` | 对应市镇几何的官方标识 |
| `match_status` | exact_code / unresolved_code |
| `members_total`、`members_matched`、`members_unresolved` | 名单数量、成功数量和缺口数量 |
| `coverage_status` | complete_by_code / partial / no_geometry |
| `area_is_partial` | 成员不齐时为 true；面积仅代表已拼出的部分 |
| `iou` | 0—1 比例，无参考时为空 |
| `fraction_inside_same_code_reference` | 某市镇面有多少比例落在同码参考内；缺市镇或参考则为空 |
| `review_status` | 全部为 pending，不伪造人工审核完成 |

CSV 使用 UTF-8 BOM，Excel 导入时应把编码列指定为文本。GeoJSON/GeoPackage 坐标为 WGS84（EPSG:4326），面积和 IoU 使用全球等积 EPSG:6933，单位为平方公里，兼顾本土、岛屿及其他名单区域。预览采用 EPSG:3035，仅用于形状对照；同一行左右图使用相同范围和比例尺，不比较不同行之间的图上大小。GeoPackage `attributes_json` 保存完整 FUA 属性。

仅使用 GISCO 几何，不上传或派生新的 GADM 图层。GISCO 的 `POP_2024` 字段没有参与经济或人口分析，不能把该字段的源值 0 当成已确认的真实人口。

## 复现与验证

在本目录运行（Python 3.11 或更新版本）：

```powershell
python -m pip install -r requirements.txt
python run_all.py
```

首次运行按 `sources.json` 下载官方快照到被 Git 忽略的 `raw/`。已有缓存先核对 SHA256；源文件变化或下线时停止并提示，不静默切换版本。之后可以使用通过校验的缓存重建。代码不依赖德国样例目录或本机用户名路径。重建会重新生成 `outputs/` 的候选结果；实际人工审核记录应另行保存和版本管理。

已验证全部源哈希、原始成员字段与前导零、唯一编码、两个缺口未被自动补齐、80 个完整和 1 个部分覆盖、81 个有效非空面。另从原始 SHP 按名单独立重建 Madrid、Barcelona、Santa Cruz de Tenerife 和部分 Melilla，核对导出面；验证 81 个 GeoPackage 几何往返、数据库完整性和缺口属性；独立重算 Madrid/Barcelona IoU，并核对 15 个缺参考结果保留为空。验证文件为 `outputs/verification.json`，它证明的是技术检查通过，不等于科研地理口径通过。

## 署名与原始数据

区域成员定义：OECD。Administrative boundaries: © EuroGeographics, Source: European Commission – Eurostat/GISCO.

- [OECD 官方城市/FUA 定义入口](https://www.oecd.org/en/data/datasets/oecd-definition-of-cities-and-functional-urban-areas.html)
- [OECD 原始成员表](https://webfs-cfe.oecd.org/files/.Stat/cities_local_areas/fua_cities_sau_mapping.csv)
- [GISCO LAU 2024 官方底图](https://gisco-services.ec.europa.eu/distribution/v2/lau/shp/LAU_RG_01M_2024_4326.shp.zip)
- [GISCO 2024 FUA 官方单位索引](https://gisco-services.ec.europa.eu/distribution/v2/urau/urau-2024-units.json)

原始大底图只在本地缓存，仓库保留复现脚本、来源登记、匹配与质量产物。数据使用遵循原来源条款。本样例使用 OECD 定义，不能宣称与仓库原有 Oxford Economics 2019 城市定义等价。
