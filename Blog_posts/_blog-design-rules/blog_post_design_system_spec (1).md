# Blog Post Design System — Spec

**Companion to:** `blog_post_design_system.json`
**Reference implementation:** `architect-post-prototype.html` ("MCP Is for Strangers")

This document defines the pattern in prose, with real examples pulled from the reference post. The JSON file is the machine-readable version of the same definitions — use it if you're generating pages from data; use this doc if you're authoring by hand or onboarding someone to the pattern.

---

## 1. Philosophy

This format exists to solve a specific tension: architectural writing needs to be **rigorous** (an ADR's problem/solution/trade-offs should be checkable, not vibes) without becoming **unreadable** (a full ADR document, read start to finish, is not something most people finish).

Three decisions follow from that:

1. **The post is the primary unit, not the ADR.** A reader arrives at an article, not a decision record. One or more ADRs live inside it as embedded, self-contained components — the page itself is never titled or headed as if it were a single document.
2. **Every embedded decision has a two-minute path and a longer path.** The two-minute path is: Problem, Solution, four trade-off axes. It's always visible, never behind a click. The longer path — context, evidence, alternatives, references — is real content, not deleted, just collapsed by default.
3. **Related decisions show their relationship, not just their existence.** When one decision creates a second one, the post shows that as a small visible tree (parent → child) with a prose sentence explaining the dependency, so a reader understands *why* the second decision exists before they read it.

---

## 2. Design Tokens

### 2.1 Color

Monochrome by default. One deliberate, scoped exception as of v1.4: `status_chip`. Everywhere else, semantic distinctions are still carried by fill, weight, or line style — never hue.

| Token | Hex | Used for |
|---|---|---|
| `paper` | `#ffffff` | Page background |
| `paper-raised` | `#fafafa` | ADR card head, ASCII diagram block, inline code background |
| `line` | `#dddddd` | Hairline dividers — field rows, impact grid seams |
| `line-strong` | `#a8a8a8` | Byline rule, dossier panel dividers, dashed rule-note border |
| `ink` | `#111111` | Primary text; emphasis borders (card border, dossier index badge); filled impact dots; status chip color for Deprecated/Superseded |
| `ink-soft` | `#555555` | Secondary text — dek, byline, impact card body copy |
| `ink-faint` | `#8a8a8a` | Tertiary text — panel labels, resting chevrons, footer note |
| `status-accepted` | `#3f7d5c` | `status_chip` only — Accepted |
| `status-rejected` | `#b33a3a` | `status_chip` only — Rejected |
| `status-new-proposal` | `#2c4870` | `status_chip` only — New Proposal |
| `status-needs-discussion` | `#a8631a` | `status_chip` only — Needs Discussion |
| `status-*-dark` (4 tokens) | see below | `adr_switcher` option text only — a darker variant per status, more legible as small dropdown text than the base tone |
| `status-*-bg` (4 tokens) | see below | `adr_card__head` background wash, matching that card's status |

| Dark variant | Hex | | Background tint | Hex |
|---|---|---|---|---|
| `status-accepted-dark` | `#2a5940` | | `status-accepted-bg` | `#e7f1ec` |
| `status-rejected-dark` | `#7d2a2a` | | `status-rejected-bg` | `#f6e8e7` |
| `status-new-proposal-dark` | `#1c2f4a` | | `status-new-proposal-bg` | `#e6ebf1` |
| `status-needs-discussion-dark` | `#744a14` | | `status-needs-discussion-bg` | `#f5ecdd` |

**Why almost no color:** color is the first thing that gets misread in a skim, and it's the first thing lost in a black-and-white print, a screenshot filter, or for a colorblind reader. Fill/weight/shape survive all three; that's still the default for everything except status. Status earns the exception because it's a small, fixed, learn-once vocabulary — four states, always the same four colors, always paired with the status name as text — where color adds real scan speed without becoming the only signal. The four hues are the muted/dark variant of each color family, not the bright version: "yellow" in particular is implemented as a dark amber (`#a8631a`), not a literal saturated yellow, because true yellow has poor legibility as small text or a thin border against white.

### 2.2 Typography

Two families, doing two different jobs — this is the most load-bearing decision in the whole system.

- **Open Sans** — the only typeface used for anything a reader is meant to *read*: the title, dek, byline, all prose, ADR card titles, field values, impact card copy.
- **IBM Plex Mono** — restricted to anything a reader is meant to *scan as structure or code*: literal code, the ASCII diagram, the ADR tree connector, and short identifiers (ADR ids, section index letters, field labels, status chip text).

If you're ever unsure which family a new element should use, ask: *is this something the reader reads, or something they use to navigate?* Reading → sans. Navigating/identifying → mono.

**Example — an ADR card head, showing both families in one line:**

```html
<span class="adr-tag">ADR</span>            <!-- mono, 11px -->
<span class="adr-id">AD-014</span>          <!-- mono, 13px, 600 -->
<h3>Reserve MCP for Genuine Ownership Boundaries</h3>  <!-- sans, 16px, 700 -->
<span class="status-chip">Proposed</span>   <!-- mono, 10.5px, 600, uppercase -->
```

The label and id are mono because you're scanning for "which decision is this." The title is sans because you're reading it.

### 2.3 Spacing & Structure

- Page content is capped at **720px**, centered — narrow enough that prose stays readable, wide enough that the impact grid and diagrams don't feel cramped.
- ADR cards use a **1px solid `ink` border** — the one place a hairline isn't enough; a card needs to read as a distinct module you could screenshot on its own.
- Collapsible content indents **34px**, aligned under the index badge, so opened content visually "belongs" to its trigger.

---

## 3. Components

### 3.1 Blog Header

The page-level header. This is the component the previous iteration of this pattern got wrong — it originally put `Architecture Decision · AD-014` here, which claimed the whole page was one document.

**Correct:**
```
Systems & Architecture                              ← kicker
MCP Is for Strangers                                ← title
A protocol for crossing a boundary you don't...     ← dek
Platform & Architecture · 29 Aug 2026 · 9 min read
  · references 2 ADR proposals                      ← byline
```

The byline's last clause (`references N ADR proposals`) is the only hint at this level that the post contains structured decisions — it's a preview, not a claim of identity.

### 3.2 Prose Block

Ordinary paragraphs, in the architect voice: direct, evidence-led, first person plural ("we"), no filler. Two hard rules:

- Every embedded ADR sequence needs a prose sentence stating *why the reader is about to see these decisions*. The switcher and first card should never just appear.
- Don't write a separate prose transition between each pair of ADRs. With `adr_switcher` in use (§3.4a), cards aren't read back-to-back in one scroll, so a per-pair transition has nowhere reliable to land — say the overall shape once, up front, and let `relation_note` (per card) and `tree_slice_view` (map) carry the rest.

**Example (from the reference post, the one-time orientation before the switcher):**

> The first decision, formalized below, draws the boundary line explicitly — when a tool is worth wrapping in a protocol server, and when it isn't. It's since grown a second and third decision underneath it. Use the selector to move between them; each card notes what it depends on, so jumping straight to a later one still makes sense on its own.

### 3.3 ASCII System Diagram

A literal monospace diagram, used only when a system's shape is genuinely easier to grasp visually than in prose — not decoration.

```
   REST route          background worker         in-process agent
       │                       │                         │
       └───────────────────────┼─────────────────────────┘
                                │
                                ▼
                     ┌────────────────────┐
                     │  ValidatorGateway   │
                     └──────────┬─────────┘
                                ▼
                     ┌────────────────────┐
                     │     Controller      │
                     └────────────────────┘
```

Rendered in a bordered `<pre>` block using `paper-raised` background, horizontally scrollable rather than wrapping, so alignment never breaks on a narrow screen.

### 3.4 ADR Switcher (v1.2)

Only one embedded ADR is ever visible in the reading flow at a time. A dropdown lets the reader move between every ADR the post embeds, and it's the reason two other things changed this version: the old inline tree connector between cards is retired, and every non-root card now carries its own `relation_note` (§3.4a) so it's self-explanatory regardless of which card a reader opens first.

**Trigger:** any post embedding 2 or more ADRs. A single-ADR post has nothing to switch between, so no switcher renders.

**Default selection:** whichever embedded ADR currently has status **Accepted** — not the root by position. A tree's settled state can move past its root (or a later decision can supersede it), so the default has to track status, not structure. It's derived at runtime from each card's own status chip rather than trusted to a hand-set `<option selected>`, specifically so the two can't quietly drift apart when a status changes and someone forgets to update the markup to match. If more than one node happens to be Accepted (a chain where several decisions have all matured), the deepest/most-recent one wins. If nothing is Accepted yet — everything still Proposed — it falls back to whatever the static markup marks as selected, which should normally be the root, since there's no settled state yet to prefer over it.

The Accepted option is also the only one annotated in its own label — calling out every other option as "not yet accepted" would be noise; calling out the one that is isn't:

```html
<div class="adr-switcher">
  <label for="adr-switcher-select">Viewing decision</label>
  <div class="select-wrap">
    <select id="adr-switcher-select">
      <option value="AD-014" class="opt-accepted" selected>AD-014 — Reserve MCP for Genuine Ownership Boundaries (Accepted)</option>
      <option value="AD-014.1" class="opt-needs-discussion">↳ AD-014.1 — Extend the Gateway as the Default In-Process Call Path (Needs Discussion)</option>
      <option value="AD-014.1.1" class="opt-new-proposal">↳↳ AD-014.1.1 — Require a Deprecation Window for Agent-Callable Methods (New Proposal)</option>
    </select>
  </div>
</div>
```

**This markup never changes — but as of v1.6, it's presented differently.** An earlier version of this spec tried to color each `<option>`'s text directly with CSS (`select option.opt-accepted { color: ... }`). That doesn't reliably work: Chrome and Safari render the *open* dropdown popup using OS-native chrome the page's CSS can't reach, so option color is silently ignored there regardless of how correct the CSS is; Firefox only partially honors it. It's a real, well-documented platform limitation, not a bug to work around with a cleverer selector.

The actual fix is to stop asking a native `<option>` to do something it structurally can't, and build a custom listbox instead — ordinary DOM (a `<button>` plus a `<ul role="listbox">`), which is fully CSS-stylable everywhere because none of it is native popup chrome. The `<select>` above stays exactly as written: it's what a no-JS visitor sees and uses directly, and it remains the source of truth the custom listbox reads from and writes back to, so `showCard`, `findAcceptedDefault`, and the `jump-to-adr` handler all keep working against `select.value` unchanged.

**Progressive enhancement now happens at two layers, not one:**

1. The `hidden` attribute that makes non-selected cards disappear must *only* ever be set at runtime — never written into static markup (unchanged from v1.2).
2. The custom button-and-listbox is never the *only* markup for the control. It's built by script on top of the real `<select>`, and only takes over — including hiding the native `<select>` itself, once it's no longer needed for either display or accessibility — if that script actually ran. A no-JS visitor gets the plain native dropdown: unstyled, but a fully working, standard form control.

```js
(function () {
  var select = document.getElementById('adr-switcher-select');
  var wrap = document.querySelector('.adr-switcher .select-wrap');
  var cards = document.querySelectorAll('.adr-card[data-adr-id]');
  if (!select || !cards.length) return;

  function showCard(id) {
    cards.forEach(function (card) {
      card.hidden = card.getAttribute('data-adr-id') !== id;
    });
    if (select.value !== id) select.value = id;
  }

  function findAcceptedDefault() { /* unchanged from v1.3 — see §3.4 */ }

  select.addEventListener('change', function () {
    showCard(select.value);
    syncTriggerLabel();     // keeps the custom button's visible text in sync
    syncListboxSelection(); // keeps aria-selected in sync on the <li> options
  });

  // jump-to-adr now sets select.value and dispatches 'change', rather than
  // calling showCard() directly — one code path updates the cards, the
  // trigger label, and the listbox's selected state together.
  document.querySelectorAll('.jump-to-adr').forEach(function (link) {
    link.addEventListener('click', function (e) {
      e.preventDefault();
      select.value = link.getAttribute('data-target');
      select.dispatchEvent(new Event('change'));
      wrap.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
  });

  function buildListbox() {
    // Builds a <button aria-haspopup="listbox"> and a <ul role="listbox">
    // with one <li role="option"> per <option>, each carrying that option's
    // opt-{status} class (copied straight from option.className) so the
    // status colors defined in CSS actually render — full keyboard support
    // (arrow keys, Enter/Space, Escape, Tab-to-close) and click-outside-to-
    // close included. See the reference implementation for the complete,
    // un-abridged version.
    //
    // Once built, select.hidden = true — the native control now exists
    // purely as the data model; the button+listbox's own ARIA covers the
    // same ground, so leaving both exposed would double-announce to
    // assistive tech.
  }

  if (wrap) buildListbox();

  showCard(findAcceptedDefault());
  syncTriggerLabel();
  syncListboxSelection();
})();
```

The reference implementation has the complete script, including the abridged `buildListbox` internals (keyboard navigation, focus management, click-outside handling) left out above for length.
```

### 3.4a Relation Note

Sits at the top of every **non-root** card's body, before the Problem/Solution fields. It exists because the switcher makes non-linear reading normal — a reader can open AD-014.1.1 first, with no guarantee they read AD-014 or AD-014.1 before it.

```html
<p class="relation-note">
  ↳↳ extends <a href="#" class="jump-to-adr" data-target="AD-014.1">AD-014.1</a> —
  closes a gap that decision opened once the agent-runtime fork started iterating
  on controller interfaces faster than the rest of the codebase.
</p>
```

The link isn't a plain in-page anchor — its target card may currently be hidden, so clicking it has to invoke the same switching logic as the dropdown (see the `jump-to-adr` handler above), not just jump to a `#fragment`.

**What replaced the old tree connector:** previously, a small `AD-014 └─ AD-014.1` element sat *between* two cards that were both visible in the scroll. Once only one card is ever visible, there's no "between" for it to sit in — `relation_note` carries that same information, but from inside the card that needs it, and `adr_switcher`'s dropdown carries the navigation. The old connector element is deprecated as a standalone piece; its literal syntax lives on only inside `tree_slice_view`'s expanded map (§3.14), which is a different, still-valid use — an overview, not a between-cards element.

### 3.5 ADR Card


The core embeddable unit. Anatomy:

```
┌─────────────────────────────────────────────────────┐
│ ADR   AD-014   Reserve MCP for Genuine...  [Proposed]│ ← head
├─────────────────────────────────────────────────────┤
│ PROBLEM   ...                                        │
│ SOLUTION  ...                                        │ ← decision summary fields
│                                                       │
│ ● improves   ○ trade-off to watch                    │ ← impact legend
│ ┌───────────┬───────────┬───────────┬───────────┐    │
│ │ Cognitive │ Perform-  │ Reliab-   │ Evolvab-  │    │ ← impact grid
│ │ Load      │ ance      │ ility     │ ility     │    │
│ └───────────┴───────────┴───────────┴───────────┘    │
│                                                       │
│ DECISION RULE                                        │
│ ✓ same codebase, runtime, owner → ...                │ ← decision rule
│ ✗ different team/company → ...                       │   (always open)
│                                                       │
│ ▸ A  Context                                         │
│ ▸ B  Rationale & Evidence                             │ ← dossier panels
│ ▸ C  Consequences                                     │   (collapsed by default)
│ ▸ D  Alternatives Considered                          │
│ ▸ E  When to Revisit                                  │
│ ▸ F  References                                       │
└─────────────────────────────────────────────────────┘
```

**Two variants:**

- **Full** — 5–6 dossier sections, for the primary/parent decision carrying most of the post's evidence. Example: AD-014 in the reference post.
- **Condensed** — 2–3 dossier sections, for a child decision that leans on its parent for shared context rather than re-explaining everything. Example: AD-014.1, which only has *Consequences* and *References*, because *Context* and *Rationale* are already covered by AD-014.

The condensed variant exists specifically so a post with several related ADRs doesn't force every one of them to carry the full six-section weight — only the decision that's actually introducing new reasoning needs to.

### 3.6 Decision Summary Fields

Two rows, Problem and Solution, always visible. Each should be readable in a single breath.

**Example:**

| Field | Value |
|---|---|
| Problem | Agents are treated as a category that always needs MCP, even when the tool they're calling already lives in the same codebase, language, and deploy as the agent itself. |
| Solution | Call internally-owned tools directly through the existing `validator_gateway` call path. Reserve MCP for tools that genuinely cross an ownership boundary. |

### 3.7 Impact Grid

Four required axes — **Cognitive Load, Performance, Reliability, Evolvability** — each capped at **50 words**. The cap is enforced editorially, not just as a guideline: if an axis needs more room to justify itself, that reasoning belongs in a dossier panel (usually *Rationale & Evidence* or *Consequences*), not in the summary.

State is shown by dot fill, never color:

- **● filled circle** — this axis improves under the proposed decision.
- **○ hollow ring** — this axis has a real trade-off worth watching.

A one-line legend explaining this convention must appear once per card, directly above the grid — don't assume the reader remembers it from a different ADR earlier in the same post.

**Example (Performance axis, 41 words):**

> Removes a serialization and IPC hop from the agent's reasoning loop. A tool call behaves like any other function call in-process — no round trip, no JSON-RPC overhead, no server startup latency on first use.

### 3.8 Decision Rule

The one component that is **never collapsible**. Format: a short heading, then binary branches marked with ✓ / ✗ (glyphs, not color), optionally followed by a secondary numeric heuristic.

**Example:**

> ✓ **Same codebase, runtime, and owner** → call it directly through the gateway. No server, no schema, no protocol.
> ✗ **Different team, company, or multiple independent clients** need the same tool → MCP is earning its keep. Build the server.
>
> *Rough secondary signal: fewer than about three independent integrations sharing a tool means the N-to-M problem MCP exists to solve hasn't shown up yet.*

### 3.9 Dossier Panel

A single collapsible section, built on native `<details>/<summary>` — no JavaScript required for open/close, full keyboard and screen-reader support for free.

**Canonical section order** (use as many as the card needs, in this order, relettered contiguously if some are omitted):

`A Context → B Rationale & Evidence → C Consequences → D Alternatives Considered → E When to Revisit → F References`

**Markup shape:**

```html
<details class="dossier-panel">
  <summary>
    <span class="dossier-index">B</span>
    <span class="dossier-title">Rationale &amp; Evidence</span>
    <span class="chevron" aria-hidden="true">›</span>
  </summary>
  <div class="dossier-content">
    <p>…</p>
  </div>
</details>
```

The chevron rotates 90° on open via a `[open]` attribute selector — a CSS-only affordance, disabled under `prefers-reduced-motion` without disabling the open/close behavior itself.

### 3.10 Status Chip

Color-coded as of v1.4 — the component was deliberately structured from v1.0 to accept this without restructuring, and it finally does:

| Status | Color | Meaning |
|---|---|---|
| New Proposal | `status-new-proposal` (dark blue) | Freshly drafted, not yet reviewed |
| Needs Discussion | `status-needs-discussion` (dark amber) | Under active review; open questions remain |
| Accepted | `status-accepted` (dark green) | Ratified, currently in effect |
| Rejected | `status-rejected` (dark red) | Reviewed and declined |
| Deprecated | none (`ink`) | Was accepted, no longer recommended — kept from the original enum, intentionally uncolored |
| Superseded | none (`ink`) | Replaced by a later decision — kept from the original enum, intentionally uncolored |

Deprecated and Superseded stay in the original ink-bordered style rather than getting a fifth and sixth color. They describe what happens to a decision *after* its active review is over, which is a different axis than the four review-stage colors above — and a six-color legend is a much heavier thing to learn than a four-color one for comparatively little gain, since a deprecated or superseded decision rarely needs to be spotted at a glance the way an urgent "needs discussion" one does.

Rendering: `1px solid {status color}` border, `{status color}` text, the small square glyph before the label in the same color. The color is reinforcement only — every chip's status is also its literal text content, so nothing is lost printed in black and white or read by a screen reader.

**As of v1.5, status also tints the card itself, not just the chip.** `adr_card__head` (the bar containing the ADR id, title, version badge, and chip) picks up a pale wash of that status's `-bg` token — light enough that the existing black heading text stays fully legible over it. The point is scannability: a reader using the switcher sees the status register at a glance from the whole card head, not only from a small chip they have to actually read.

### 3.11 Footer Note

One closing line naming every embedded ADR id, for when the post is skimmed bottom-up or shared as a bare link:

> Platform & Architecture · this post embeds AD-014 and AD-014.1 · prototype layout, static HTML/CSS

### 3.12 Version Badge

A small bordered tag naming the committed system version, commit, or fork an ADR is bound to — `main @ a3f9c1e`, `agent-runtime @ f6b21d0`, `v2.1.0`. Mono type, `ink-soft` text, `ink-faint` border, no fill — deliberately quieter than a status chip, since it's context rather than a state the reader needs to act on.

**Required** on any card that's part of a tree deeper than one parent/child pair. Optional elsewhere. The format itself is free-form on purpose — git-SHA, semver, and fork-name are all valid conventions, and this system doesn't pick one for you. Pick one per post and stay consistent inside it.

### 3.13 References at Scale

Resolves the open question from the first version of this spec: per-card References panels work fine for two ADRs, but get repetitive once a post embeds several, especially when they cite overlapping sources.

**Trigger:** 3 or more embedded ADR cards, or 5+ unique references across all cards — whichever comes first.

**Rule:** this component *supplements*, never *replaces*, each card's own References dossier panel. A single ADR card must stay independently readable without the reader having to scroll elsewhere — that principle from section 3.9 doesn't change. What this adds is a single deduplicated index for a reader who's read the whole post and wants one list, with each entry noting which decision(s) it backs:

```html
<details class="scale-panel">
  <summary>All References (3)</summary>
  <ul>
    <li>AMD ROCm Blog, "Enabling Physical AI Agents with Lemonade" — cited in AD-014, AD-014.1.1</li>
    <li>validator_gateway package build plan (internal) — cited in AD-014, AD-014.1</li>
    <li>Agent-runtime fork RFC (internal) — cited in AD-014.1.1</li>
  </ul>
</details>
```

Collapsed by default, positioned immediately after the last ADR card and before the closing prose.

### 3.14 Tree Slice View

An overview map, independent of the switcher (§3.4a) — expanding it doesn't change which card is visible below it. Reserved for when a tree has real depth or breadth; for a simple parent/child pair, the switcher's dropdown plus the child's `relation_note` already say enough.

**Trigger:** depth > 2 (a grandchild or deeper) or breadth > 1 (more than one child off the same parent). A simple one-parent-one-child post skips this — the switcher and relation note cover it.

**Position:** once per post, after the intro and system diagram, before the switcher — it's a map of the territory, read before the territory itself.

**Shape:** a single collapsed dropdown, labeled with the node and layer count, expanding to a layered list where indentation encodes depth and every node carries its version badge:

```
▸ View full decision tree (3 nodes · 3 layers)
```

expanded:

```
AD-014                                    [main @ a3f9c1e]
 └─ AD-014.1   extends                    [main @ a3f9c1e]
      └─ AD-014.1.1   extends             [agent-runtime @ f6b21d0]
```

**Why the version badge matters here specifically:** a tree that's three layers deep usually spans real time — the grandchild decision was very possibly made against a different state of the system than its grandparent. AD-014.1.1 in the example above is bound to a later fork (`agent-runtime`) than AD-014 and AD-014.1 (`main`), which tells a reader orienting themselves in the tree something a plain parent/child label can't: *this branch of decisions only applies from this system state onward.* Without the badge, a deep tree shows lineage; with it, a deep tree shows lineage *and* when each link in that lineage became true.

Every node in the tree slice must correspond to either an embedded `adr_card` or an explicitly declared `relationships.target` — never a decision the post doesn't otherwise reference. This keeps the map honest: it can only ever be a compressed view of content that's actually present, not a promise of content that isn't.

---

## 4. Content Model

A post is:

```
blog_header
prose_block             (intro — one-time orientation if 2+ ADRs follow)
ascii_system_diagram    (optional)
tree_slice_view          (only if tree depth > 2 or breadth > 1 — see §3.14)
adr_switcher              (only if the post embeds 2+ ADRs — see §3.4)
adr_card                  (relation_note as its first body element if non-root; only
                            one visible at a time once adr_switcher is present — §3.4/3.4a)   × N
references_at_scale     (only if >= 3 ADR cards or >= 5 unique references — see §3.13)
prose_block             (closing)
footer_note
```

An ADR card's underlying data shape (see JSON `content_model.adr_card_schema` for the full field-level spec):

```json
{
  "id": "AD-014.1",
  "status": "Proposed",
  "title": "Extend the Gateway as the Default In-Process Call Path for Agents",
  "problem": "…",
  "solution": "…",
  "impact": { "cognitive_load": "…", "performance": "…", "reliability": "…", "evolvability": "…" },
  "decision_rule": { "branches": [ { "mark": "✓", "condition": "…" } ], "secondary_signal": null },
  "sections": [ { "index": "A", "title": "Consequences", "content": "…" } ],
  "relationships": [ { "type": "extends", "target": "AD-014" } ],
  "system_ref": "main @ a3f9c1e"
}
```

`system_ref` is optional on a standalone card or a simple one-level parent/child pair, and required once a card is part of a tree that triggers `tree_slice_view` (§3.14) — otherwise the layer view has nothing to show next to that node.

This shape is deliberately close to a real ADR's fields — the point of the format is that nothing about the underlying decision record changes; only its presentation gets a two-minute path bolted onto the front of it.

---

## 5. Authoring Rules (quick reference)

- Never title the page itself as an ADR. The page is the post; the ADR is a component.
- Every impact axis ≤ 50 words. If it needs more, that's a sign the reasoning belongs in a dossier panel.
- Decision Rule is always open. Everything else defaults to collapsed.
- Section index letters reflect true order and are renumbered contiguously if a section is dropped for a condensed card.
- Only one adr_card is visible at a time once a post embeds 2 or more — switch via `adr_switcher`, never by stacking cards in the scroll.
- `adr_switcher` defaults to whichever card is Accepted, not to the root — derive this from status at runtime, never hand-set it as a static default.
- Every non-root adr_card opens with a `relation_note` — never assume the reader arrived via its parent.
- No color is used to carry meaning anywhere. If you need a third semantic state beyond "improves / watch," add a third dot style (e.g. a half-filled or dashed ring) before reaching for color.
- Mono type only for code, diagrams, and identifiers — never for prose a reader is meant to actually read start to finish.

---

## 6. Accessibility

- All interactive elements show a visible `2px solid ink` focus outline on `:focus-visible`.
- Collapsibles use native `<details>/<summary>` — keyboard operable and screen-reader-announced with no custom ARIA required.
- `prefers-reduced-motion` disables the chevron rotation transition specifically; it never disables or delays the open/close state itself.
- Because the palette is monochrome by construction, there is no color-only information to fail a contrast or colorblindness check in the first place.
- `status_chip` (v1.4) is the one exception, and it's deliberately non-color-dependent: every chip's status is present as text inside the element, so removing color entirely — grayscale rendering, a colorblind reader, a black-and-white printout — loses nothing.
- `adr_switcher` is the one component requiring JavaScript. Its `hidden`-attribute toggling is applied only at runtime (§3.4), so a no-JS visitor gets every embedded ADR in document order — a complete fallback, not a broken one. The `<select>` itself is a native form control, so keyboard and screen-reader support come for free once JS is running.

---

## 7. Resolved Questions

**v1.1**

- **Reference lists at scale — resolved.** Per-card References stay (§3.9/3.13) for independent readability; a post-level, deduplicated, collapsed-by-default **References at Scale** dropdown (§3.13) is added once a post reaches 3 ADRs or 5+ unique sources. It supplements rather than replaces the per-card panels.
- **Deeper trees — resolved.** Once a tree exceeds a simple parent/child pair (a grandchild, or more than one child off a parent), a page-level **Tree Slice View** (§3.14) renders the full relevant subtree by layer, collapsed by default. Every node in it carries a **version badge** (§3.12) — a required `system_ref` field once a card is part of such a tree — so a reader can tell not just how decisions relate, but which committed state of the system each one was bound to.

**v1.2**

- **One ADR visible at a time — resolved.** Every post embedding 2+ ADRs now uses **ADR Switcher** (§3.4) to show exactly one at a time, defaulting to the root/parent decision. This retires `adr_tree_connector` as a between-cards element (its syntax survives only inside `tree_slice_view`'s map) and introduces **Relation Note** (§3.4a) so a card opened out of order — via the switcher or a direct link — is still self-explanatory. This is the first component in the system requiring JavaScript, with progressive enhancement treated as mandatory rather than a nice-to-have.

**v1.3**

- **Default should track status, not position — resolved.** `adr_switcher` no longer defaults to the root by structure; it defaults to whichever card currently has status Accepted, read live from that card's status chip rather than a hardcoded `<option selected>`. This matters once a tree outlives its root — a decision further down the chain can become the settled, current state while its root remains merely the starting point of the reasoning. The root is still the sensible fallback when nothing in the tree has been Accepted yet, since there's no settled state to prefer over it in that case.

**v1.4**

- **Status chip color — resolved.** `status_chip` moved from purely monochrome to a fixed four-color palette: New Proposal (dark blue), Needs Discussion (dark amber, standing in for "yellow" — see §2.1 on why not literal yellow), Accepted (dark green), Rejected (dark red). Deprecated and Superseded deliberately stay uncolored — they describe post-review lifecycle, a different axis than the four review-stage colors, and adding two more hues for infrequently-spotted states wasn't worth the added palette to learn. Color is reinforcement only: status is always also literal text in the chip, so nothing is lost in grayscale, print, or for a colorblind reader (§6).

**v1.5**

- **Status coding extended to the card head — resolved.** `adr_card__head` picks up a pale wash (`status-{name}-bg`) matching that card's status, so status registers from the whole card title bar, not just a small chip a reader has to find and read.
- **Status coding on the switcher's options — attempted, corrected in v1.6.** This version tried to color `<option>` text directly via CSS (`select option.opt-accepted { color: ... }`). That doesn't reliably work — see v1.6 below.

**v1.6**

- **Dropdown option colors — corrected.** v1.5's CSS-on-`<option>` approach was wrong: Chrome and Safari render an open `<select>` dropdown with OS-native chrome the page's CSS cannot reach, so option color is silently ignored there; Firefox only partially honors it. This is a real platform limitation, not something a more specific selector fixes. The actual solution replaces the *presentation* of the switcher with a custom listbox — a `<button aria-haspopup="listbox">` plus a `<ul role="listbox"><li role="option">` per option, ordinary DOM that's fully stylable everywhere — while the native `<select>` stays in the markup unchanged as the source of truth and the no-JS fallback (§3.4). Worth remembering for any future colored-per-item control in this system: native form-control internals (`<option>`, and by the same logic parts of `<input type="range">`, native `<progress>`, etc.) are frequently not stylable the way they appear to be in isolated testing, and the fix is a custom-built equivalent layered on top of the real control, not a cleverer selector.

## 8. Open Questions for Future Versions

- **`system_ref` format standardization:** currently free-form (git-SHA, semver, or fork name all valid) — left flexible since teams version differently, but this means two posts in the same publication could adopt different conventions. Worth revisiting if this pattern is used across more than one team.
- **Deep-linking to a specific ADR:** the switcher currently has no URL-hash sync (e.g. `#AD-014.1.1` pre-selecting that card on load), so a link to "this specific decision" from outside the post always lands on the Accepted default and requires a manual switch. Worth adding if these posts get linked to at the ADR level often.
- **Tree slice depth in practice:** the reference implementation now exercises a 3-layer chain (AD-014 → AD-014.1 → AD-014.1.1). A tree with real breadth (two or more children off one parent, rendered together) hasn't been built yet, only described — the layout for simultaneous depth *and* breadth in the same slice may need another pass once a real case exists.
- **A tree with more than one Accepted node:** `adr_switcher`'s default-selection rule picks the deepest Accepted node in document order when several are Accepted, but this hasn't been exercised against a real multi-Accepted tree yet — only specified.
