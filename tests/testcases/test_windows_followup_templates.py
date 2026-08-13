from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(relative_path):
    return (ROOT / relative_path).read_text(encoding='utf-8')


def test_file_import_controls_are_native_buttons():
    template = read('templates/roots/top_menu.html')

    for control_id in [
        'load-input-images-button',
        'load-input-folder-button',
        'load-annotations-button',
        'load-exclude-masks-button',
    ]:
        assert 'id="{}"'.format(control_id) in template
    assert template.count('type="button"') >= 6
    assert 'aria-disabled="true"' in template


def test_settings_actions_are_keyboard_focusable():
    template = read('templates/roots/modals.html')

    assert 'aria-label="Close settings"' in template
    assert '<button type="button" class="ui negative button"' in template
    assert '<button type="button" class="ui positive right labeled icon button"' in template


def test_windows_workflow_uploads_only_the_full_portable_zip():
    workflow = read('.github/workflows/build.yml')

    assert 'actions/checkout@v5' in workflow
    assert 'actions/setup-python@v6' in workflow
    assert 'actions/upload-artifact@v6' in workflow
    assert 'path: builds/*_DigIT_RootDetector.zip' in workflow
    assert 'path: builds/*.zip' not in workflow
