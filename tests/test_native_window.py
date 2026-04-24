"""Native window hit-test helpers."""

from apps.shell.native_window import bubble_visual_hit_test, live2d_visual_hit_test


def test_bubble_visual_hit_test_uses_circle_not_square():
    assert bubble_visual_hit_test(112, 112, 56, 56) is True
    assert bubble_visual_hit_test(112, 112, 10, 56) is True
    assert bubble_visual_hit_test(112, 112, 0, 0) is False
    assert bubble_visual_hit_test(112, 112, 111, 111) is False


def test_live2d_visual_hit_test_uses_capsule_fallback():
    assert live2d_visual_hit_test(420, 680, 210, 340) is True
    assert live2d_visual_hit_test(420, 680, 210, 260) is True
    assert live2d_visual_hit_test(420, 680, 210, 100) is False
    assert live2d_visual_hit_test(420, 680, 12, 12) is False
    assert live2d_visual_hit_test(420, 680, 410, 340) is False


def test_live2d_visual_hit_test_prefers_reported_ellipse_region():
    region = {"kind": "ellipse", "x": 0.25, "y": 0.2, "width": 0.5, "height": 0.6}

    assert live2d_visual_hit_test(400, 600, 200, 300, region) is True
    assert live2d_visual_hit_test(400, 600, 60, 300, region) is False


def test_live2d_visual_hit_test_uses_alpha_mask_region():
    region = {
        "kind": "alpha_mask",
        "x": 0.25,
        "y": 0.25,
        "width": 0.5,
        "height": 0.5,
        "cols": 4,
        "rows": 4,
        "mask": "0110011001100110",
    }

    assert live2d_visual_hit_test(400, 600, 170, 210, region) is True
    assert live2d_visual_hit_test(400, 600, 110, 210, region) is False


def test_live2d_visual_hit_test_keeps_capsule_fallback_when_region_is_too_narrow():
    region = {"kind": "ellipse", "x": 0.45, "y": 0.45, "width": 0.1, "height": 0.1}

    assert live2d_visual_hit_test(400, 600, 200, 300, region) is True


def test_live2d_visual_hit_test_uses_silhouette_inside_reported_model_bounds():
    region = {"kind": "live2d", "x": 0.2, "y": 0.2, "width": 0.6, "height": 0.7}

    assert live2d_visual_hit_test(400, 600, 200, 290, region) is True
    assert live2d_visual_hit_test(400, 600, 305, 290, region) is False
