---
name: Privelto
description: A calm, practical document workspace carried into a local-first desktop download site.
colors:
  paper: "#f5f6f8"
  ink: "#172033"
  muted: "#505c70"
  blue: "#1d3f8f"
  line: "#d5dbe5"
  pale: "#e4ebf7"
  white: "#fff"
  blue-hover: "#142e6e"
  focus: "#416bcd"
  download-surface: "#e8edf6"
  highlight: "#fff0cc"
typography:
  display:
    fontFamily: "Plex, sans-serif"
    fontSize: "clamp(42px, 4.6vw, 64px)"
    fontWeight: 600
    lineHeight: 1.075
    letterSpacing: "-.035em"
  headline:
    fontFamily: "Plex, sans-serif"
    fontSize: "clamp(30px, 3.1vw, 43px)"
    fontWeight: 500
    lineHeight: 1.15
    letterSpacing: "-.035em"
  body:
    fontFamily: "Plex, sans-serif"
    lineHeight: 1.65
  legal-title:
    fontFamily: "Plex, sans-serif"
    fontSize: "clamp(36px, 5vw, 52px)"
    lineHeight: 1.1
    letterSpacing: "-.035em"
  legal-body:
    fontFamily: "Plex, sans-serif"
    fontSize: "17px"
    lineHeight: 1.75
  label:
    fontFamily: "PlexMono, monospace"
    fontSize: "12px"
    fontWeight: 400
rounded:
  language: "5px"
  button: "6px"
  demonstration: "12px"
spacing:
  gutter-desktop: "64px"
  gutter-tablet: "36px"
  gutter-mobile: "24px"
components:
  button-primary:
    backgroundColor: "{colors.blue}"
    textColor: "{colors.white}"
    rounded: "{rounded.button}"
    padding: "14px 23px"
  button-primary-hover:
    backgroundColor: "{colors.blue-hover}"
  button-inverse:
    backgroundColor: "{colors.white}"
    textColor: "{colors.blue}"
    rounded: "{rounded.button}"
    padding: "14px 23px"
  demonstration:
    backgroundColor: "{colors.pale}"
    rounded: "{rounded.demonstration}"
  document:
    backgroundColor: "{colors.white}"
    textColor: "{colors.ink}"
    padding: "27px 30px 18px"
---

# Design System: Privelto

## Overview

**Creative North Star: "The Clear Document Desk"**

Privelto inherits the desktop application's IBM Plex typography and navy accent. The website feels composed, legible and practical: cool paper surfaces, restrained borders, direct headings and explicit actions. Its strongest visual object is a white document, rather than an abstract privacy illustration.

The fictional document demonstration makes a change visible while keeping the surrounding content readable. Technical details use a small amount of monospace type; generous section spacing keeps the download and setup information approachable. English, Spanish, Galician, French, German, Italian and Portuguese share the same visual system.

**Key Characteristics:**

- IBM Plex Sans for reading; IBM Plex Mono for document and release metadata.
- Navy actions against cool, light surfaces.
- Flat section structure with a single lifted document sheet.
- A reversible, clearly labeled fictional example.

## Colors

The palette combines a sober navy accent with cool paper, white sheets and muted text.

### Primary

- **Desk Navy** (`blue`): primary buttons, emphasized headline words, links and the closing call to action. The darker hover token signals an actionable state.
- **Focus Blue** (`focus`): visible keyboard outlines, distinct from ordinary borders.

### Neutral

- **Cool Paper** (`paper`): the page background.
- **Document Ink** (`ink`): headings, primary text and redacted example fields.
- **Slate Text** (`muted`): explanatory copy that remains readable on paper.
- **Quiet Rule** (`line`): navigation, method and FAQ dividers.
- **Pale Desk** (`pale`): the demonstration frame.
- **Download Wash** (`download-surface`): the download and setup region.
- **White Sheet** (`white`): document paper and the inverse closing button.
- **Review Highlight** (`highlight`): visible fictional private fields before the demonstration is toggled.

**The Meaningful Accent Rule.** Use navy to identify actions or emphasis. Keep long reading passages in ink or slate.

## Typography

**Display and body font:** IBM Plex Sans, served locally as `Plex`, with a sans-serif fallback.

**Metadata font:** IBM Plex Mono, served locally as `PlexMono`, with a monospace fallback.

The sans-serif is clear and slightly technical without overwhelming the document metaphor. Monospace is reserved for release versions, references, page metadata and replacement labels.

### Hierarchy

- **Display:** semibold, tight leading and negative tracking; the main proposition uses the frontmatter display token. Wide screens above the large breakpoint use a larger fixed display size.
- **Headline:** medium weight, balanced wrapping and tight tracking; major section headings use the headline token.
- **Title:** method and setup headings are medium weight (20px); platform names are larger (23px).
- **Body:** paragraph leading follows the body token. Hero supporting copy is larger (18px) with a compact measure (48ch); method and FAQ copy is smaller (14px).
- **Label:** release metadata uses the monospace label token. Navigation and action labels use Plex Sans at medium weight.
- **Legal reading:** legal titles use the dedicated responsive title token; section headings are medium-weight (26px desktop; 24px mobile) with comfortable leading (1.3). Paragraphs use the legal body token, reducing to 16px on mobile; update metadata is smaller (14px).
- **Document detail:** the miniature sheet deliberately uses smaller type to look like a complete record. Preserve the adjacent readable explanation and control.

## Layout

The shared page container has a maximum width (1320px). Desktop gutters follow the frontmatter desktop token. The header is a single horizontal row (100px high). The hero has two balanced columns, copy on the left and a document demonstration on the right, separated by a substantial gap (70px; 95px on wide screens).

Method headings use two columns and the three steps form a horizontal row. Downloads combine a platform table with a separate setup column. Each platform pairs an installable package with a portable package in two equal action columns. A dedicated requirements section follows, with eight definition rows in a two-column grid. FAQ headings sit beside a stack of disclosures. Borders and background changes identify sections without enclosing each item in a card.

At the tablet breakpoint (1050px), gutters and gaps shrink, and each platform heading moves above its paired download choices. At the mobile breakpoint (760px), gutters use the mobile token and the hero, headings, steps, download/setup area, requirements and FAQ become single columns. The demonstration stays centered with a bounded width (510px). The two package choices remain side by side, each with its own size and checksum beneath. Platform and architecture share a compact heading row. The closing call to action and footer stack vertically. How-it-works and requirements navigation links are hidden; downloads and the native language selector remain visible. Document headings allow word wrapping and automatic hyphenation so longer translations fit the sheet. At 380px and below, header section anchors are hidden to retain the brand and language selector without overflow; the prominent hero download action remains visible.

Legal, privacy, cookies and accessibility pages use a single reading column rather than the landing page hero grid. Their container is bounded (1100px), with sections and paragraphs limited to a readable measure (72ch) and titles to a shorter measure (22ch). The reading page inherits the existing vertical padding (75px above, 90px below; 48px on mobile). Sections start with generous separation (42px; 34px mobile). Long translated titles and owner values wrap within the available width. These pages retain the shared header, language selector and permanent footer.

## Elevation & Depth

The page is predominantly flat. Tonal surfaces, thin rules and whitespace do most of the grouping. Only the white document sheet receives an ambient shadow (`0 8px 24px #20396216`), distinguishing the sheet from its pale desk. Buttons and content rows do not float above the page.

**The Sheet Rule.** Reserve the existing ambient shadow for the document object; use spacing and rules for ordinary content.

## Shapes

Buttons have gently curved corners using the button radius token. The demonstration has a softer outer frame using its own radius token; the sheet itself keeps square corners. The language select uses the smaller language radius. Dividers are thin and continuous. Small circular markers indicate trust-list items and demonstration status.

## Components

### Buttons

Solid navy buttons use white medium-weight labels, a compact radius and clear spacing. The default button has a minimum height (48px); the hero and closing action use a larger target (54px). Package and demonstration controls use a compact height (43px). The closing action reverses the colors against a navy section.

Hover changes the background over a short transition (.18s). All interactive elements share a visible keyboard outline (3px with 5px offset). Reduced-motion preferences remove transitions and smooth scrolling. Download and checksum links have unique accessible names containing the platform, architecture and localized package kind. Visible action labels use localized installable/portable terminology appropriate to each language.

### Navigation

A lowercase wordmark, compact mark and navy period anchor the header. Plain medium-weight links gain navy color and an underline on hover. The language switch is a native bordered select with seven self-named options: English, Español, Galego, Français, Deutsch, Italiano and Português. It uses a localized accessible label and preserves the page type when changing language. Its minimum height is compact (36px), with a bounded width (127px desktop; 112px mobile). A skip link appears on keyboard focus. Mobile navigation preserves downloads and language selection without introducing a menu drawer.

### Document demonstration

The pale frame contains a heading and status dot, a white fictional record and a full-width toggle. Four private fields—name, email, reference and date—start as warm highlights. Toggling replaces all four displayed values with readable monospace labels on dark ink backgrounds and updates the button's pressed state and live status message. Keep the fictional-data note visible. This is an illustrative state change, not a visitor document processor.

### Download rows

Each bordered row presents platform and architecture alongside paired installable and portable choices. Both actions have equal width; each has its own size and checksum line beneath it. Version metadata and evidence links sit nearby, while first-launch setup information occupies its own column. These are flat rows rather than repeated raised cards. Package sizes come from release artifacts and are not design tokens.

### Requirements

A dedicated section uses a definition list with eight rows: Windows, macOS, Linux, memory, storage, optional advanced AI, portable use, and internet/offline use. Medium-weight terms (20px) introduce muted explanations (14px, line-height 1.7). Thin top borders separate the entries. Two columns use a broad desktop gap (64px; 36px at tablet); mobile uses one column. Keep requirements readable in the page flow rather than hiding them inside disclosures.

### FAQ disclosures

Native disclosures use medium-weight questions, a navy plus/minus indicator and a single lower divider. Expanded text uses the standard muted body style. Keep full question text and keyboard behavior intact.

### Legal reading pages

Legal content uses plain headings, paragraphs and source lists on the cool paper background, without decorative cards or certification marks. Paragraphs have a clear lower margin (20px). Source lists use readable text (16px, line-height 1.8). A navy text link returns to the landing page after the reading content.

The owner definition list appears on legal and privacy pages. Thin top rules divide entries; medium-weight terms occupy a fixed desktop column (180px) beside flexible values, separated by a gap (20px). Mobile stacks terms and values with a smaller gap (5px). Terms wrap long words with language-aware hyphenation; values preserve intentional line breaks and wrap long content. Component previews use illustrative identity values rather than claiming confirmed operator details.

### Permanent footer

Every page links to the four legal routes—legal, privacy, cookies and accessibility—in its current language, alongside source code and contact links. Seven language editions provide 28 legal reading routes. The expanded link group remains a wrapping row, bounded to a practical width (600px), with readable links (14px). Desktop aligns the group to the right of the brand; mobile places it below the brand and aligns it left. The license line remains smaller and muted. Preserve ordinary underlined link affordances and the global keyboard focus outline.

These visual patterns indicate access to information, not legal or accessibility certification. Contractual verification, including the account-specific hosting DPA, is tracked separately in COMPLIANCE.md.

## Do's and Don'ts

### Do:

- **Do** retain IBM Plex and the inherited navy identity when adding surfaces.
- **Do** keep text, controls and document examples as real HTML.
- **Do** preserve clear focus states, native disclosure behavior and reduced-motion support.
- **Do** use fictional data in demonstrations and keep its label visible.
- **Do** carry the same hierarchy and localized accessible names across all seven languages.
- **Do** keep all four legal links permanently reachable and allow long translated labels to wrap.

### Don't:

- **Don't** replace the document-led visual with unrelated stock privacy imagery.
- **Don't** add shadows to every section, download row or FAQ item.
- **Don't** introduce a document upload control into the marketing site.
- **Don't** use the demonstration's visual success state to imply perfect automatic detection.
