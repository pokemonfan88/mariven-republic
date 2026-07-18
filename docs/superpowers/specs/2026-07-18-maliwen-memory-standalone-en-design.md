# Maliwen National Memory Centre 英文单文件版设计

## 目标

基于已完成的 `maliwen-memory/maliwen-memory-standalone.html`，制作独立英文版 `maliwen-memory/maliwen-memory-standalone-en.html`。英文版保持中文版的完整内容、视觉、照片和原生交互，但所有面向访客的文字采用自然、正式的英文纪念馆文体，不使用生硬逐字翻译。

## 文件与依赖

- 中文版保持不变。
- 英文版是一个独立、自包含的 HTML 文件。
- CSS、JavaScript、10 张照片和 168 条名录数据全部内嵌。
- 不引用 React、Vite、Tailwind 运行时、CDN、在线字体或任何外部资源。
- 可通过 `file://` 离线打开，也可部署到普通静态服务器。

## 内容范围

英文版完整保留以下内容：首屏、独立之光、裂痕、第一次内战、1987—1989 年内战、名录墙、证词厅、战后重建、宪法序言、今日纪念和页脚。标题、正文、引文、照片说明、档案编号、筛选按钮、状态标签、无结果提示和架空世界观声明全部翻译。

英文文案使用适合历史博物馆、国家纪念馆和真相委员会档案的庄重语气。专有名词固定译法如下：

- 马里文国家记忆中心：National Memory Centre of Maliwen
- 真相与和解委员会：Truth and Reconciliation Commission (TRC)
- 大地之眼：Eye of the Land / Matanivanua
- 五月运动：May Movement / Mai ni Mee
- 马里文解放军：Maliwen Liberation Army (MLA)
- 卡托拉：Katora
- 马卡迪岛：Makadi Island
- 蒂莫岛：Timo Island
- 佩拉岛：Pela Island
- 鲁瓦岛：Ruwa Island

## 名录

英文版沿用中文版完全相同的 168 条人物记录、年龄、日期、岛屿、身份和族群比例，不重新生成数据。姓名只显示拉丁字母原名；华裔人物显示汉语拼音。

身份译法为 Civilian、Government Forces 和 May Movement。日期显示为英文档案格式，例如 `3 May 1987`。搜索支持拉丁字母姓名和英文岛名，筛选项为 All、Katora、Makadi Island、Timo Island、Pela Island 和 Ruwa Island。

## 视觉与交互

英文版与中文版保持相同的深蓝黑、暖金色档案馆视觉和响应式断点。保留阅读进度、渐入、数字递增、名录搜索、岛屿组合筛选、证词展开、键盘焦点和 `prefers-reduced-motion` 支持。

## 验证标准

- HTML 的 `lang` 为 `en`，页面标题和描述为英文。
- 文件包含 10 个叙事部分、10 张内嵌照片和 168 条固定名录。
- 页面不存在访客可见的中文字符；人物拼音和马里文专有名词保持拉丁字母。
- 姓名、族群比例和中文版本完全一致。
- 英文姓名、英文岛名搜索及组合筛选正确。
- 文件不存在外部脚本、样式、图片或字体引用。
- 桌面和手机宽度无横向溢出，浏览器控制台无错误。
- 原中文版文件内容及校验结果不变。
