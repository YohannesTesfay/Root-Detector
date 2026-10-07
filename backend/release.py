"""Package version and manual GitHub release discovery.

The application never downloads or runs an update. A user can open a published
release after finishing work and closing the local process.
"""

import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.request


REPOSITORY = 'YohannesTesfay/Root-Detector'
INSTALLER_ASSET = 'RootDetector-Windows-Setup.exe'
PORTABLE_ASSET = 'RootDetector-Windows-portable.zip'
VERSION_PATTERN = re.compile(r'^v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-rc\.([1-9][0-9]*))?$')
MAX_RESPONSE_BYTES = 256 * 1024


def version_key(value):
    """Compare release candidates before their corresponding final release."""
    match = VERSION_PATTERN.fullmatch(value) if isinstance(value, str) else None
    if not match:
        return None
    major, minor, patch, candidate = match.groups()
    return (int(major), int(minor), int(patch), 0 if candidate else 1,
            int(candidate) if candidate else 0)


def package_info(root=None):
    if root is None:
        root = os.environ.get('ROOT_PATH') or str(Path(__file__).resolve().parent.parent)
    root = Path(root)
    try:
        with (root / 'release.json').open('r', encoding='utf-8') as source:
            metadata = json.load(source)
    except (OSError, ValueError):
        return {'version': None, 'channel': None, 'repository': REPOSITORY,
                'package': 'unknown'}
    if not isinstance(metadata, dict):
        return {'version': None, 'channel': None, 'repository': REPOSITORY,
                'package': 'unknown'}
    version = metadata.get('version')
    channel = metadata.get('channel')
    key = version_key(version)
    if (key is None or channel not in ('preview', 'stable')
            or (channel == 'preview') != (key[3] == 0)
            or metadata.get('repository') != REPOSITORY):
        return {'version': None, 'channel': None, 'repository': REPOSITORY,
                'package': 'unknown'}
    return {'version': version, 'channel': channel, 'repository': REPOSITORY,
            'package': 'installer' if (root / 'INSTALL-MODE.txt').is_file()
            else 'portable' if (root / 'BUILD-INFO.txt').is_file() else 'source'}


def _published_release(release, current_key, channel, required_asset):
    if not isinstance(release, dict) or release.get('draft') is not False:
        return None
    tag = release.get('tag_name')
    candidate_key = version_key(tag)
    if candidate_key is None or candidate_key <= current_key:
        return None
    if channel == 'stable' and candidate_key[3] == 0:
        return None
    if release.get('prerelease') is not (candidate_key[3] == 0):
        return None
    assets = release.get('assets')
    if not isinstance(assets, list):
        return None
    available = {item.get('name') for item in assets if isinstance(item, dict)
                 and item.get('state') == 'uploaded'}
    if required_asset not in available:
        return None
    # Build the public URL ourselves; do not relay untrusted API URLs to the browser.
    return {'version': tag[1:] if tag.startswith('v') else tag,
            'url': 'https://github.com/{}/releases/tag/{}'.format(REPOSITORY, tag)}


def find_update(info, open_url=urllib.request.urlopen):
    current_key = version_key(info.get('version'))
    if current_key is None or info.get('channel') not in ('preview', 'stable'):
        return {'status': 'unavailable', 'message': 'This build has no comparable release version.'}
    required_asset = INSTALLER_ASSET if info.get('package') == 'installer' else PORTABLE_ASSET
    endpoint = 'https://api.github.com/repos/{}/releases?per_page=20'.format(REPOSITORY)
    request = urllib.request.Request(endpoint, headers={
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'RootDetector-update-check',
    })
    try:
        with open_url(request, timeout=5) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except (OSError, urllib.error.URLError, TimeoutError):
        return {'status': 'unavailable', 'message': 'Could not reach GitHub Releases. Check the connection and retry.'}
    if len(raw) > MAX_RESPONSE_BYTES:
        return {'status': 'unavailable', 'message': 'GitHub returned a response that was too large.'}
    try:
        releases = json.loads(raw.decode('utf-8'))
    except (ValueError, UnicodeError):
        releases = None
    if not isinstance(releases, list):
        return {'status': 'unavailable', 'message': 'GitHub returned an unexpected release response.'}
    candidates = [candidate for candidate in (
        _published_release(item, current_key, info['channel'], required_asset) for item in releases[:20]
    ) if candidate]
    if not candidates:
        return {'status': 'current', 'version': info['version']}
    newest = max(candidates, key=lambda item: version_key(item['version']))
    return {'status': 'available', 'version': newest['version'], 'url': newest['url']}
