import io
import json
import urllib.error

from backend import release


def published(tag, *, prerelease=False, assets=True, draft=False):
    filenames = [release.INSTALLER_ASSET, release.PORTABLE_ASSET] if assets else []
    return {'tag_name': tag, 'draft': draft, 'prerelease': prerelease,
            'html_url': 'https://elsewhere.example/unsafe',
            'assets': [{'name': name, 'state': 'uploaded'} for name in filenames]}


def response_for(items):
    payload = json.dumps(items).encode('utf-8')
    return lambda request, timeout: io.BytesIO(payload)


def test_installed_version_reads_package_not_user_copy(tmp_path):
    (tmp_path / 'release.json').write_text(json.dumps({
        'version': '0.1.0-rc.1', 'channel': 'preview',
        'repository': release.REPOSITORY,
    }), encoding='utf-8')
    (tmp_path / 'INSTALL-MODE.txt').write_text('installed', encoding='utf-8')
    assert release.package_info(tmp_path)['package'] == 'installer'
    assert release.package_info(tmp_path)['version'] == '0.1.0-rc.1'
    (tmp_path / 'release.json').write_text('invalid', encoding='utf-8')
    assert release.package_info(tmp_path)['version'] is None
    (tmp_path / 'release.json').write_text('[]', encoding='utf-8')
    assert release.package_info(tmp_path)['version'] is None
    (tmp_path / 'release.json').write_text(json.dumps({
        'version': '0.1.0', 'channel': 'preview', 'repository': release.REPOSITORY,
    }), encoding='utf-8')
    assert release.package_info(tmp_path)['version'] is None


def test_preview_finds_newest_complete_published_release():
    info = {'version': '0.1.0-rc.1', 'channel': 'preview'}
    items = [published('v2026-09-02-rc1', prerelease=True),
             published('v0.1.0-rc.2', prerelease=True, assets=False),
             published('v0.1.0-rc.3', prerelease=True, draft=True),
             published('v0.1.0-rc.4', prerelease=True),
             published('v0.1.0'), published('v0.2.0-rc.1', prerelease=True)]
    found = release.find_update(info, open_url=response_for(items))
    assert found == {'status': 'available', 'version': '0.2.0-rc.1',
                     'url': 'https://github.com/YohannesTesfay/Root-Detector/releases/tag/v0.2.0-rc.1'}


def test_stable_ignores_preview_and_requires_complete_release():
    info = {'version': '0.1.0', 'channel': 'stable'}
    assert release.find_update(info, open_url=response_for([
        published('v0.2.0-rc.1', prerelease=True),
        published('v0.2.0', assets=False),
    ])) == {'status': 'current', 'version': '0.1.0'}
    assert release.find_update(info, open_url=response_for([
        published('v0.2.0'),
    ]))['version'] == '0.2.0'


def test_update_requires_the_asset_matching_the_current_package():
    portable_only = published('v0.2.0')
    portable_only['assets'] = [portable_only['assets'][1]]
    installer_only = published('v0.3.0')
    installer_only['assets'] = [installer_only['assets'][0]]
    releases = response_for([portable_only, installer_only])
    assert release.find_update({'version': '0.1.0', 'channel': 'stable',
                                'package': 'portable'}, open_url=releases)['version'] == '0.2.0'
    assert release.find_update({'version': '0.1.0', 'channel': 'stable',
                                'package': 'installer'}, open_url=releases)['version'] == '0.3.0'


def test_offline_and_unexpected_release_data_are_not_updates():
    info = {'version': '0.1.0-rc.1', 'channel': 'preview'}
    def offline(_request, timeout):
        raise urllib.error.URLError('offline')
    assert release.find_update(info, open_url=offline)['status'] == 'unavailable'
    assert release.find_update(info, open_url=response_for({'message': 'rate limited'}))['status'] == 'unavailable'
    assert release.find_update(info, open_url=response_for([
        published('v0.2.0', prerelease=True),
    ]))['status'] == 'current'


def test_update_endpoint_requires_local_session_token(monkeypatch, tmp_path):
    from backend.app import App
    from backend import settings
    monkeypatch.setenv('DO_NOT_RELOAD', '1')
    monkeypatch.setenv('INSTANCE_PATH', str(tmp_path))
    monkeypatch.setattr(settings, 'ensure_pretrained_models', lambda: None)
    app = App()
    monkeypatch.setattr(release, 'find_update', lambda _info: {'status': 'current'})
    client = app.test_client()
    assert client.post('/api/updates/check', headers={'Host': 'localhost'}).status_code == 403
    response = client.post('/api/updates/check', headers={
        'Host': 'localhost', 'Origin': 'http://localhost/',
        'X-RootDetector-Token': app.session_token,
    })
    assert response.status_code == 200
    assert response.get_json()['status'] == 'current'
