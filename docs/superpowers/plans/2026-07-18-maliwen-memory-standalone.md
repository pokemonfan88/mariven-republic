# 马里文国家记忆中心原生单文件版实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付一个无需 React、构建工具、外部资源或网络连接即可打开的 `maliwen-memory-standalone.html`，保留现有网站视觉和交互，并用 168 条固定、文化一致的双语姓名替换随机名录。

**Architecture:** 最终 HTML 由语义化正文、内联 CSS、JSON 名录数据和原生 JavaScript 四部分组成。照片在最终化步骤中转换为 Base64 `data:` URL；Node.js 内置模块编写的校验脚本把 HTML 当作交付物检查，不成为运行依赖。

**Tech Stack:** HTML5、CSS3、原生 JavaScript、Node.js 20 内置模块、浏览器 `IntersectionObserver` 与 `requestAnimationFrame`

## Global Constraints

- 最终交付路径固定为 `maliwen-memory/maliwen-memory-standalone.html`。
- 现有 `maliwen-memory` React 项目、依赖和构建产物不得修改或删除。
- 最终 HTML 不得包含外部样式表、外部脚本、CDN、远程字体或非 `data:` 图片地址。
- 页面必须保留现有 10 个叙事部分、10 张照片、滚动进度、渐入、数字递增、搜索和岛屿筛选。
- 名录固定为 168 条：原住民马里文人 134、印度裔 20、欧洲裔 6、华裔 4、其他太平洋族群 4。
- 每条名录必须包含唯一的中文姓名、唯一的原文拼写、岛屿、年龄、死亡日期、身份和族群。
- 平民在每个族群中占多数，不把任何族群与固定交战方绑定。
- 页面必须明确注明马里文及人物档案属于架空历史世界观。
- 最终文件可通过 `file://` 双击离线运行，并支持 `prefers-reduced-motion`。

---

## 文件结构

- Create: `maliwen-memory/maliwen-memory-standalone.html` — 唯一用户交付物；包含 HTML、CSS、JSON 数据、原生 JavaScript 和 Base64 图片。
- Create: `maliwen-memory/scripts/verify-standalone.mjs` — 开发期静态校验器；检查结构、名录、外部引用和内嵌资源。
- Reference only: `maliwen-memory/src/sections/Narrative.tsx` — 前五幕正文和照片说明来源。
- Reference only: `maliwen-memory/src/sections/Voices.tsx` — 证词、重建、今日与页脚来源。
- Reference only: `maliwen-memory/src/data/memorial.ts` — 统计、证词和重建数据来源；旧姓名生成器不复用。
- Reference only: `maliwen-memory/src/assets/photos/*.jpg` — 10 张需要 Base64 内嵌的照片。

### Task 1: 建立可测试的原生页面骨架和视觉系统

**Files:**
- Create: `maliwen-memory/maliwen-memory-standalone.html`
- Create: `maliwen-memory/scripts/verify-standalone.mjs`

**Interfaces:**
- Produces: `#reading-progress`、10 个 `section[data-act]`、`.reveal`、`.count-up[data-value]`、`#victim-data`、`#victim-search`、`#island-filters`、`#victim-list` 和 `#victim-count`。
- Consumes: 当前 React 页面中的中文正文、标题、引文、照片说明和档案编号，不改写历史叙事。

- [ ] **Step 1: 写入会失败的结构校验器**

创建 `maliwen-memory/scripts/verify-standalone.mjs`，首版包含：

```js
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const htmlUrl = new URL('../maliwen-memory-standalone.html', import.meta.url)
const html = await readFile(htmlUrl, 'utf8')

assert.match(html, /<!doctype html>/i)
assert.match(html, /<html lang="zh-CN">/)
assert.equal((html.match(/<section\b[^>]*data-act=/g) ?? []).length, 10)
assert.match(html, /id="reading-progress"/)
assert.match(html, /id="victim-data" type="application\/json"/)
assert.match(html, /id="victim-search"/)
assert.match(html, /id="island-filters"/)
assert.match(html, /id="victim-list"/)
assert.match(html, /prefers-reduced-motion:\s*reduce/)
assert.match(html, /架空历史世界观/)

console.log('standalone structure: PASS')
```

- [ ] **Step 2: 运行结构校验并确认失败**

Run: `node maliwen-memory/scripts/verify-standalone.mjs`

Expected: FAIL with `ENOENT` because `maliwen-memory-standalone.html` does not exist.

- [ ] **Step 3: 创建语义化 HTML 和完整内联 CSS**

建立 `maliwen-memory/maliwen-memory-standalone.html`。在 `<head>` 内定义颜色、排版、容器、档案照片、数据卡片、时间轴、名录网格、证词卡片、按钮焦点、移动端断点和减少动态效果规则。关键选择器契约为：

```html
<div id="reading-progress" aria-hidden="true"><span></span></div>
<main>
  <section class="hero" data-act="hero"><h1>158,000 个名字</h1></section>
  <section data-act="independence"><h2>独立之光</h2></section>
  <section data-act="fracture"><h2>裂痕</h2></section>
  <section data-act="first-war"><h2>第一次内战：部落与共和国</h2></section>
  <section data-act="abyss"><h2>深渊：兄弟之战</h2></section>
  <section data-act="wall"><h2>名录墙</h2></section>
  <section data-act="voices"><h2>证词库</h2></section>
  <section data-act="rebirth"><h2>灰烬上的房子</h2></section>
  <section data-act="constitution"><h2>《马里文共和国宪法》序言</h2></section>
  <section data-act="today"><h2>今日 · 2026</h2></section>
</main>
```

必须逐段迁移 `Narrative.tsx` 和 `Voices.tsx` 的可见中文内容；照片暂时使用精确占位符 `{{PHOTO:filename.jpg}}`，供 Task 4 机械内嵌。所有 `.reveal` 元素在默认 HTML 中可见，只有 `<html class="js">` 后才进入等待动画状态，以保证脚本失败时正文仍可阅读。

- [ ] **Step 4: 运行结构校验并确认通过**

Run: `node maliwen-memory/scripts/verify-standalone.mjs`

Expected: `standalone structure: PASS`

- [ ] **Step 5: 浏览器核对静态页面**

Run: `npm run dev -- --host 127.0.0.1` from `maliwen-memory`，打开 `http://127.0.0.1:3000/maliwen-memory-standalone.html`。

Expected: 10 个部分顺序正确；桌面端与现有 React 首页在配色、标题层级、正文宽度和照片比例上接近；控制台无错误。

- [ ] **Step 6: 提交页面骨架**

```powershell
git add -- maliwen-memory/maliwen-memory-standalone.html maliwen-memory/scripts/verify-standalone.mjs
git commit -m "feat: add native memory centre page structure"
```

### Task 2: 策划并校验 168 条固定双语名录

**Files:**
- Modify: `maliwen-memory/maliwen-memory-standalone.html`
- Modify: `maliwen-memory/scripts/verify-standalone.mjs`

**Interfaces:**
- Produces: `VictimRecord[]` JSON，字段为 `nameZh`、`nameLatin`、`ethnicity`、`island`、`age`、`date`、`side`。
- Consumes: Task 1 的空 `script#victim-data[type="application/json"]`。

- [ ] **Step 1: 扩展校验器并确认空数据失败**

在校验器加入 JSON 提取和严格断言：

```js
const dataMatch = html.match(
  /<script id="victim-data" type="application\/json">([\s\S]*?)<\/script>/,
)
assert.ok(dataMatch, 'victim JSON block is missing')
const victims = JSON.parse(dataMatch[1])

assert.equal(victims.length, 168)
assert.equal(new Set(victims.map((v) => v.nameZh)).size, 168)
assert.equal(new Set(victims.map((v) => v.nameLatin)).size, 168)

const expectedEthnicities = {
  indigenous: 134,
  indian: 20,
  european: 6,
  chinese: 4,
  pacific: 4,
}
const actualEthnicities = Object.fromEntries(
  Object.keys(expectedEthnicities).map((key) => [
    key,
    victims.filter((v) => v.ethnicity === key).length,
  ]),
)
assert.deepEqual(actualEthnicities, expectedEthnicities)

for (const victim of victims) {
  assert.match(victim.nameZh, /\S+/)
  assert.match(victim.nameLatin, /^[A-Za-z' -]+$/)
  assert.ok(['卡托拉', '马卡迪岛', '蒂莫岛', '佩拉岛', '鲁瓦岛'].includes(victim.island))
  assert.ok(Number.isInteger(victim.age) && victim.age >= 8 && victim.age <= 78)
  assert.match(victim.date, /^198[789]\.\d{2}\.\d{2}$/)
  assert.ok(['平民', '政府军', '五月运动'].includes(victim.side))
}

for (const ethnicity of Object.keys(expectedEthnicities)) {
  const group = victims.filter((v) => v.ethnicity === ethnicity)
  assert.ok(group.filter((v) => v.side === '平民').length > group.length / 2)
}

console.log('victim records: PASS')
```

Run: `node maliwen-memory/scripts/verify-standalone.mjs`

Expected: FAIL at `victims.length` because the data block is empty.

- [ ] **Step 2: 写入 134 条原住民马里文记录**

逐条策划姓名并写入 JSON。姓名采用同一音系，显示样式为 `莱萨·纳武阿（Leisa Navua）`。允许同岛少量共享家族姓氏，但完整中文名和拉丁名都不得重复。原住民组至少 68 条为平民，且政府军与五月运动两方均有记录。

- [ ] **Step 3: 写入 34 条其他族群记录**

加入 20 条印度裔、6 条欧洲裔、4 条华裔和 4 条其他太平洋族群记录。各组的名与姓必须属于同一文化命名体系；华裔原文拼写使用汉语拼音。每组平民数量严格超过该组一半。

- [ ] **Step 4: 运行名录校验**

Run: `node maliwen-memory/scripts/verify-standalone.mjs`

Expected:

```text
standalone structure: PASS
victim records: PASS
```

- [ ] **Step 5: 人工抽查姓名文化一致性**

分别抽查原住民 20 条、印度裔 10 条、欧洲裔 6 条、华裔 4 条、其他太平洋族群 4 条。检查中文音译与拉丁拼写对应、无跨文化随机拼接、无重复完整姓名。

- [ ] **Step 6: 提交固定名录**

```powershell
git add -- maliwen-memory/maliwen-memory-standalone.html maliwen-memory/scripts/verify-standalone.mjs
git commit -m "feat: curate bilingual Maliwen memorial names"
```

### Task 3: 实现无依赖原生交互

**Files:**
- Modify: `maliwen-memory/maliwen-memory-standalone.html`
- Modify: `maliwen-memory/scripts/verify-standalone.mjs`

**Interfaces:**
- Consumes: `VictimRecord[]` from `#victim-data`。
- Produces: `normalizeSearch(value)`、`renderVictims()`、`setIslandFilter(island)`、`initReveal()`、`initCounters()`、`updateProgress()`。

- [ ] **Step 1: 添加交互函数存在性测试并确认失败**

```js
for (const functionName of [
  'normalizeSearch',
  'renderVictims',
  'setIslandFilter',
  'initReveal',
  'initCounters',
  'updateProgress',
]) {
  assert.match(html, new RegExp(`function\\s+${functionName}\\s*\\(`))
}
```

Run: `node maliwen-memory/scripts/verify-standalone.mjs`

Expected: FAIL because `normalizeSearch` is not present.

- [ ] **Step 2: 实现名录渲染、搜索和筛选**

在内联脚本中实现以下状态和函数：

```js
const victims = JSON.parse(document.querySelector('#victim-data').textContent)
const state = { query: '', island: '全部' }

function normalizeSearch(value) {
  return value.normalize('NFKD').toLocaleLowerCase('zh-CN').trim()
}

function renderVictims() {
  const query = normalizeSearch(state.query)
  const filtered = victims.filter((victim) => {
    const matchesIsland = state.island === '全部' || victim.island === state.island
    const haystack = normalizeSearch(`${victim.nameZh} ${victim.nameLatin} ${victim.island}`)
    return matchesIsland && (!query || haystack.includes(query))
  })
  victimList.replaceChildren(...filtered.map(createVictimCard))
  victimCount.textContent = `${filtered.length} / ${victims.length} 条记录`
  emptyState.hidden = filtered.length !== 0
}

function setIslandFilter(island) {
  state.island = island
  for (const button of filterButtons) {
    const active = button.dataset.island === island
    button.classList.toggle('active', active)
    button.setAttribute('aria-pressed', String(active))
  }
  renderVictims()
}
```

`createVictimCard()` 必须使用 `document.createElement` 和 `textContent`，不可把 JSON 值直接拼入 `innerHTML`。

- [ ] **Step 3: 实现进度条、渐入和数字递增**

```js
function updateProgress() {
  const root = document.documentElement
  const maximum = root.scrollHeight - root.clientHeight
  const ratio = maximum > 0 ? root.scrollTop / maximum : 0
  progressFill.style.transform = `scaleX(${Math.min(1, Math.max(0, ratio))})`
}

function initReveal() {
  if (reduceMotion.matches || !('IntersectionObserver' in window)) {
    document.querySelectorAll('.reveal').forEach((node) => node.classList.add('shown'))
    return
  }
  const observer = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue
      entry.target.classList.add('shown')
      observer.unobserve(entry.target)
    }
  }, { threshold: 0.15 })
  document.querySelectorAll('.reveal').forEach((node) => observer.observe(node))
}

function initCounters() {
  const counters = document.querySelectorAll('.count-up[data-value]')
  const showFinal = (node) => {
    const value = Number(node.dataset.value)
    node.textContent = value.toLocaleString('en-US') + (node.dataset.suffix || '')
  }
  if (reduceMotion.matches || !('IntersectionObserver' in window)) {
    counters.forEach(showFinal)
    return
  }
  const observer = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting || entry.target.dataset.counted === 'true') continue
      const node = entry.target
      node.dataset.counted = 'true'
      const target = Number(node.dataset.value)
      const suffix = node.dataset.suffix || ''
      const startedAt = performance.now()
      const tick = (now) => {
        const progress = Math.min(1, (now - startedAt) / 1800)
        const eased = 1 - Math.pow(1 - progress, 3)
        node.textContent = Math.round(target * eased).toLocaleString('en-US') + suffix
        if (progress < 1) requestAnimationFrame(tick)
        else showFinal(node)
      }
      requestAnimationFrame(tick)
      observer.unobserve(node)
    }
  }, { threshold: 0.4 })
  counters.forEach((node) => observer.observe(node))
}
```

数字动画实现必须使用三次缓出 `1 - Math.pow(1 - progress, 3)`，结束时调用 `showFinal(node)`，避免舍入后显示错误。

- [ ] **Step 4: 运行静态校验并在浏览器验证交互**

Run: `node maliwen-memory/scripts/verify-standalone.mjs`

Expected: 所有静态校验通过。

浏览器验证：输入一个中文姓氏、一个拉丁姓氏和一个岛屿名，结果分别变化；选择“鲁瓦岛”后再输入姓名，结果为两者交集；清空搜索并选“全部”恢复 `168 / 168`；滚动时进度条与数字动画工作；控制台无错误。

- [ ] **Step 5: 提交原生交互**

```powershell
git add -- maliwen-memory/maliwen-memory-standalone.html maliwen-memory/scripts/verify-standalone.mjs
git commit -m "feat: add standalone memorial interactions"
```

### Task 4: 内嵌照片并完成离线、响应式和无障碍验收

**Files:**
- Modify: `maliwen-memory/maliwen-memory-standalone.html`
- Modify: `maliwen-memory/scripts/verify-standalone.mjs`

**Interfaces:**
- Consumes: 10 个 `{{PHOTO:filename.jpg}}` 占位符和 `src/assets/photos/*.jpg`。
- Produces: 无任何外部资源引用的最终独立 HTML。

- [ ] **Step 1: 添加独立文件资源校验并确认失败**

```js
assert.equal((html.match(/{{PHOTO:[^}]+}}/g) ?? []).length, 0)
assert.equal((html.match(/<img\b/g) ?? []).length, 10)
assert.equal((html.match(/<img\b[^>]*src="data:image\/jpeg;base64,/g) ?? []).length, 10)
assert.doesNotMatch(html, /<(?:script|link)\b[^>]*(?:src|href)="https?:/i)
assert.doesNotMatch(html, /<link\b[^>]*rel="stylesheet"/i)
assert.doesNotMatch(html, /url\(["']?https?:/i)
console.log('embedded assets: PASS')
```

Run: `node maliwen-memory/scripts/verify-standalone.mjs`

Expected: FAIL because photo placeholders remain.

- [ ] **Step 2: 机械替换 10 个图片占位符**

使用一次性 Node 命令读取每张 JPEG 为 Base64，并把 `{{PHOTO:filename.jpg}}` 替换为 `data:image/jpeg;base64,...`。替换前断言每个占位符只出现一次，替换后断言没有剩余占位符；不要改变图片像素或重新压缩。

- [ ] **Step 3: 运行完整静态校验**

Run: `node maliwen-memory/scripts/verify-standalone.mjs`

Expected:

```text
standalone structure: PASS
victim records: PASS
embedded assets: PASS
```

- [ ] **Step 4: 验证普通构建未被破坏**

Run: `npm run build` from `maliwen-memory`

Expected: TypeScript 与 Vite 构建成功，现有 `dist` 继续生成。

- [ ] **Step 5: 进行浏览器桌面验收**

以 1280×720 视口打开独立页面。检查首屏、每个章节起点、全部照片、名录墙、证词区和浅色结尾；页面无横向滚动，控制台无错误，168 条名录可搜索筛选。

- [ ] **Step 6: 进行浏览器移动端与减少动态效果验收**

以 390×844 视口检查标题不截断、正文可读、筛选按钮换行、名录为单列、照片不溢出。启用 `prefers-reduced-motion: reduce` 后重新加载，确认正文与最终数字直接显示，搜索筛选仍可用。

- [ ] **Step 7: 进行真正离线文件验收**

断开页面网络访问，直接打开 `file:///D:/马里文/maliwen-memory/maliwen-memory-standalone.html`。确认 10 张照片、样式、168 条名录及全部交互正常，开发者工具网络面板没有 HTTP/HTTPS 请求。

- [ ] **Step 8: 最终提交**

```powershell
git add -- maliwen-memory/maliwen-memory-standalone.html maliwen-memory/scripts/verify-standalone.mjs
git commit -m "feat: deliver offline Maliwen memory centre"
```
