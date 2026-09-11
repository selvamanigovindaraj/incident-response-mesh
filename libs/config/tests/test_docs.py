from config.docs import render_markdown


def test_render_markdown_includes_app_settings_section() -> None:
    output = render_markdown()
    assert "# Configuration Reference" in output
    assert "## AppSettings" in output


def test_render_markdown_includes_nested_subsystem_sections() -> None:
    output = render_markdown()
    assert "## QueueSettings" in output
    assert "backend" in output
    assert "redis_url" in output


def test_render_markdown_includes_field_descriptions_when_present() -> None:
    output = render_markdown()
    assert "service_name" in output
