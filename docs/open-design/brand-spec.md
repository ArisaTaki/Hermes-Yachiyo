# Hermes-Yachiyo Phase 3 Brand Spec

Reference source: https://www.hermes-yachiyo.dev/

## Visual Tokens

```css
:root {
  --bg:      oklch(17.6% 0.014 258.4); /* #0d1117 */
  --surface: oklch(21.5% 0.023 254.3); /* #121a24 */
  --fg:      oklch(96.1% 0.008 236.6); /* #edf3f7 */
  --muted:   oklch(78.1% 0.022 252.5); /* #aeb9c6 */
  --border:  oklch(32.6% 0.034 257.1); /* #293546 */
  --accent:  oklch(51.1% 0.086 186.4); /* #0f766e */

  --font-display: -apple-system, BlinkMacSystemFont, "SF Pro Display", "Inter", "Segoe UI", system-ui, sans-serif;
  --font-body:    -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", "Segoe UI", system-ui, sans-serif;
  --font-mono:    "SF Mono", "Berkeley Mono", ui-monospace, Menlo, Consolas, monospace;
}
```

## Observed Product Values

- Source dark mode uses `#0d1117`, `#111827`, `#161f2b`, `#121a24`, and `#0f1720` as layered desktop surfaces.
- Source accent is teal: `#0f766e`, with `#14b8a6` and `rgba(20, 184, 166, .14)` as active or soft states.
- Source warning and destructive accents are restrained: amber `#f59e0b` / `#b45309`, rose `#be123c`.
- Product screenshots use macOS title bars, large rounded app windows, 8px panel radii, thick dark borders, and dense dashboard cards.
- The current IA is centered on local readiness: Hermes runtime, Workspace, Bridge, tools, chat, Bubble, Live2D, Doctor, backup, and uninstall.

## Layout Posture

- Mac-native shell first: visible title bar, traffic lights, local status, and window-level navigation.
- Dashboard density over marketing composition: left navigation, central setup/workbench, right inspector/status rail.
- Accent budget stays low: teal marks ready/local states and the current onboarding step; violet can remain only as a Linear-inspired interactive hint.
- Cards are functional panels, not decorative tiles: 8px radii, translucent dark fills, one-pixel borders, no heavy shadows.
- Yachiyo warmth appears through copy, Bubble/Live2D presence, and soft moonlit contrast, not anime-heavy backgrounds.
