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


def test_training_can_be_closed_or_retried_after_interruption():
    template = read('templates/roots/modals.html')
    training = read('frontend/roots/training.js')
    training_tab = read('templates/roots/training_tab.html')

    assert 'id="retry-training-button"' in template
    assert 'id="close-training-button"' in template
    assert 'Training interrupted. You can retry' in training
    assert '<button type="button" class="ui violet basic fluid button"' in training_tab
    assert 'for="training-learning-rate"' in training_tab
    assert 'for="training-number-of-epochs"' in training_tab


def test_pipeline_cancel_waits_for_backend_acknowledgement():
    template = read('templates/roots/modals.html')
    pipeline = read('frontend/roots/pipeline.js')

    assert 'class="ui red button" id="pipeline-cancel-button"' in template
    assert 'Cancelling analysis. Waiting for the active operation to stop safely' in pipeline
    assert "run.state == 'cancelling'" in pipeline


def test_windows_workflow_uploads_only_the_full_portable_zip():
    workflow = read('.github/workflows/build.yml')

    assert 'actions/checkout@v5' in workflow
    assert 'actions/setup-python@v6' in workflow
    assert 'actions/upload-artifact@v6' in workflow
    assert 'path: builds/*_DigIT_RootDetector.zip' in workflow
    assert 'path: builds/*.zip' not in workflow


def test_portable_build_contains_exact_provenance():
    build_script = read('build.py')

    assert "os.environ.get('GITHUB_SHA'" in build_script
    assert "os.environ.get('GITHUB_RUN_ID'" in build_script
    assert "build_dir+'/BUILD-INFO.txt'" in build_script


def test_training_help_is_user_facing_and_cli_alias_stays_technical():
    template = read('templates/roots/training_tab.html')
    technical_guide = read('TECHNICAL-GUIDE.md')

    assert '--lr' not in template
    assert '--lr' in technical_guide
