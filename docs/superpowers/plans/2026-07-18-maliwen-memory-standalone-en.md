# Maliwen National Memory Centre English Standalone Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a self-contained English edition of the Maliwen National Memory Centre while preserving the Chinese standalone file unchanged.

**Architecture:** Transform a copy of the verified Chinese standalone HTML with a controlled translation map for narrative and interface copy, then convert the embedded victim JSON to English display fields. Retain the existing inline CSS, images, and dependency-free interaction code, adjusting selectors and labels only where English localization requires it.

**Tech Stack:** HTML5, CSS3, vanilla JavaScript, Node.js 20 built-in modules

## Global Constraints

- Output: `maliwen-memory/maliwen-memory-standalone-en.html`.
- Do not modify `maliwen-memory/maliwen-memory-standalone.html`.
- Preserve 10 sections, 10 embedded images, 168 fixed victims, and ethnicity counts 134/20/6/4/4.
- Display victim names only with `nameLatin`; display Chinese names as Pinyin already stored in `nameLatin`.
- Translate all visitor-visible interface and narrative copy into natural English.
- Preserve native search, filtering, progress, reveal, counters, testimony toggles, responsive layout, keyboard focus, and reduced-motion behavior.
- Do not introduce external assets or runtime dependencies.

---

### Task 1: Add English-output validation

**Files:**
- Create: `maliwen-memory/scripts/verify-standalone-en.mjs`
- Create: `maliwen-memory/maliwen-memory-standalone-en.html`

**Interfaces:**
- Consumes: final English HTML.
- Produces: structural, data, language, embedded-resource, and interaction assertions.

- [ ] Write a validator that asserts `lang="en"`, English title and controls, 10 sections, 10 data-URL images, 168 victims, fixed ethnicity counts, required vanilla functions, no external resources, and no `nameZh` rendering in `createVictimCard()`.
- [ ] Run `node scripts/verify-standalone-en.mjs` and confirm `ENOENT` before the English file exists.
- [ ] Commit the failing validator only with `test: add English standalone validation`.

### Task 2: Translate the complete narrative and archive interface

**Files:**
- Create: `maliwen-memory/maliwen-memory-standalone-en.html`

**Interfaces:**
- Consumes: the full structure, styles, scripts, and images from the Chinese standalone file.
- Produces: ten fully translated English narrative sections with English metadata, quotations, captions, archive labels, buttons, status text, and fiction notice.

- [ ] Copy the Chinese standalone file to the English output path without changing the source file.
- [ ] Replace document metadata and every visible Chinese narrative/interface string using the terminology in the approved design.
- [ ] Translate dates, number labels, testimony metadata, memorial notices, and footer copy into idiomatic English museum prose.
- [ ] Run the validator and confirm that only victim-data localization assertions remain failing.

### Task 3: Localize the victim directory and native interactions

**Files:**
- Modify: `maliwen-memory/maliwen-memory-standalone-en.html`

**Interfaces:**
- Consumes: the embedded 168-record JSON array.
- Produces: English `island` and `side` fields while retaining original `nameLatin`, `ethnicity`, `age`, and `date` data.

- [ ] Map Katora, Makadi Island, Timo Island, Pela Island, and Ruwa Island without changing record distribution.
- [ ] Map Civilian, Government Forces, and May Movement without changing record distribution.
- [ ] Render only `nameLatin`, format dates as `D Month YYYY`, and update count/no-result messages.
- [ ] Confirm Latin-name search, island search, island buttons, and combined filtering in a browser.
- [ ] Run the validator and obtain all PASS results.

### Task 4: Verify parity, responsive layout, and independence

**Files:**
- Verify: `maliwen-memory/maliwen-memory-standalone-en.html`
- Verify: `maliwen-memory/maliwen-memory-standalone.html`

**Interfaces:**
- Produces: final evidence that both language editions work independently.

- [ ] Run `node scripts/verify-standalone.mjs` and `node scripts/verify-standalone-en.mjs`.
- [ ] Run `npm run build` to ensure the original React project remains healthy.
- [ ] Inspect English desktop and 390px mobile layouts; assert no horizontal overflow and no console errors.
- [ ] Confirm the two HTML files each contain 10 Base64 JPEGs and no HTTP/HTTPS resource URLs.
- [ ] Report both output paths and file sizes.
