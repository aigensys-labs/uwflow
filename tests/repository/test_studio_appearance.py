"""Tests for Policy Studio themes, typography and local preference persistence."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "modules/policy-studio/frontend/src"


def test_policy_studio_exposes_four_themes_and_four_readable_text_sizes() -> None:
    appearance = (FRONTEND / "lib/appearance.ts").read_text(encoding="utf-8")
    app = (FRONTEND / "App.tsx").read_text(encoding="utf-8")
    for theme in ("black", "navy", "pro-white", "neat-silver"):
        assert f"id: '{theme}'" in appearance
    for text_size in ("compact", "comfortable", "large", "extra-large"):
        assert f"id: '{text_size}'" in appearance
    assert "scale: 1.15" in appearance
    assert "scale: 1.3" in appearance
    assert "scale: 1.45" in appearance
    assert "Settings2" in app
    assert "aria-pressed={preferences.theme === theme.id}" in app
    assert "aria-pressed={preferences.textSize === size.id}" in app


def test_studio_appearance_is_browser_local_and_separate_from_policy_data() -> None:
    appearance = (FRONTEND / "lib/appearance.ts").read_text(encoding="utf-8")
    app = (FRONTEND / "App.tsx").read_text(encoding="utf-8")
    doc = (ROOT / "docs/studio/policy-studio.md").read_text(encoding="utf-8")
    assert "uwflow.policy-studio.appearance.v1" in appearance
    assert "window.localStorage.getItem" in appearance
    assert "window.localStorage.setItem" in appearance
    assert "Changes apply immediately" in app
    assert "They do not change policies, candidates or runtime output" in app
    assert (
        "not written to the repository, policy JSON, candidate manifests or runtime configuration"
        in doc
    )


def test_stage_one_hard_gates_editor_uses_full_available_content_width() -> None:
    css = (FRONTEND / "styles.css").read_text(encoding="utf-8")
    dmn_block = re.search(r"\.dmn-editor\s*\{([^}]+)\}", css)
    toolbar_rule = re.search(r"\.dmn-toolbar\s*\{([^}]+)\}", css)
    assert dmn_block is not None and toolbar_rule is not None
    assert re.search(r"width:\s*100%", dmn_block.group(1))
    assert re.search(r"min-width:\s*0", dmn_block.group(1))
    assert re.search(r"width:\s*100%", toolbar_rule.group(1))
    assert "width: min(50%, 820px)" not in css
    assert "width: 72%" not in css


def test_studio_css_scales_font_sizes_and_defines_all_four_theme_palettes() -> None:
    css = (FRONTEND / "styles.css").read_text(encoding="utf-8")
    for theme in ("black", "navy", "pro-white", "neat-silver"):
        assert f'data-theme="{theme}"' in css
    assert "var(--uwflow-text-scale, 1)" in css
    assert "font-size: calc(" in css
    assert ".settings-dialog" in css
    assert ".theme-choice-grid" in css


def test_routing_canvas_edge_labels_respect_the_selected_text_size() -> None:
    routing = (FRONTEND / "components/RoutingEditor.tsx").read_text(encoding="utf-8")
    css = (FRONTEND / "styles.css").read_text(encoding="utf-8")
    assert "fontSize: 'calc(10px * var(--uwflow-text-scale, 1))'" in routing
    assert '.app-shell[data-theme="pro-white"] .flow-canvas .react-flow__edge-text' in css
    assert '.app-shell[data-theme="neat-silver"] .flow-node-top' in css
