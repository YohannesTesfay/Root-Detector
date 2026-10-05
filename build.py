#!/bin/python
import os, shutil, sys, subprocess
import datetime
import argparse, zipfile, glob
from runtime_manifest import validate_bundled_dlls, write_runtime_manifest

parser = argparse.ArgumentParser()
parser.add_argument('--zip', action='store_true')
parser.add_argument('--prune-torchlibs', action='store_true')
parser.add_argument('--installer-payload', action='store_true')
args = parser.parse_args()
if args.installer_payload and args.prune_torchlibs:
    parser.error('An installed package must include its complete PyTorch runtime.')
if args.installer_payload and args.zip:
    parser.error('Build the portable ZIP separately so it never contains an install marker.')
if args.installer_payload:
    import torch
    if sys.platform != 'win32' or torch.__version__ != '1.10.1+cu113' or torch.version.cuda != '11.3':
        parser.error('The Windows installer must include CPU and GPU support. Install '
                     'requirements-runtime-windows.txt after requirements.txt before building.')
os.environ['DO_NOT_RELOAD'] = 'true'
from backend.app import App
App().recompile_static(force=True)        #make sure the static/ folder is up to date

build_name = '%s_DigIT_RootDetector'%(datetime.datetime.now().strftime('%Y-%m-%d_%Hh%Mm%Ss') )
build_dir = (
    'builds/RootDetector-Windows-installer-payload'
    if args.installer_payload else 'builds/%s' % build_name
)
if os.path.exists(build_dir):
    parser.error('Build destination already exists: {}'.format(build_dir))

rc = subprocess.call(f'''pyinstaller --noupx                            \
              --hidden-import=sklearn.utils._cython_blas     \
              --hidden-import=skimage.io._plugins.tifffile_plugin   \
              --hidden-import=torchvision                           \
              --additional-hooks-dir=./hooks                        \
              --distpath {build_dir} main.py''')
if rc!=0:
    print(f'PyInstaller exited with code {rc}')
    sys.exit(rc)

shutil.copytree('static', build_dir+'/static')
os.makedirs(build_dir+'/models/')
shutil.copy('models/pretrained_models.txt', build_dir+'/models/')
if 'linux' in sys.platform:
    os.symlink('/main/main', build_dir+'/main.run')
elif not args.installer_payload:
    launcher = (
        '@echo off\n'
        'cd /d "%~dp0"\n'
        'set "ROOT_PATH=%~dp0"\n'
        'main\\main.exe %*\n'
        'pause\n'
    )
    open(build_dir+'/StartRootDetector.bat', 'w').write(launcher)

repository = os.environ.get('GITHUB_REPOSITORY', 'local/source build')
commit = os.environ.get('GITHUB_SHA', '')
if not commit:
    try:
        commit = subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'],
            universal_newlines=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = 'unknown'
run_id = os.environ.get('GITHUB_RUN_ID', 'local')
run_url = (
    'https://github.com/{}/actions/runs/{}'.format(repository, run_id)
    if run_id != 'local' and repository != 'local/source build'
    else 'local build'
)
build_info = (
    '{}\n'
    'Repository: {}\n'
    'Commit: {}\n'
    'Build UTC: {}\n'
    'GitHub Actions run: {}\n'
    'Package: {}\n'
).format(
    'RootDetector installer preview' if args.installer_payload else 'RootDetector portable build',
    repository,
    commit,
    datetime.datetime.utcnow().replace(microsecond=0).isoformat() + 'Z',
    run_url,
    'per-user installer payload with bundled PyTorch 1.10.1, CUDA 11.3 and CPU support'
    if args.installer_payload else 'full portable ZIP (the legacy partial update ZIP is not published)',
)
open(build_dir+'/BUILD-INFO.txt', 'w').write(build_info)
if args.installer_payload:
    torch_libs = os.path.join(build_dir, 'main', 'torch', 'lib')
    validate_bundled_dlls(os.path.join(os.path.dirname(torch.__file__), 'lib'), torch_libs)
    write_runtime_manifest(torch_libs, 'cu113')
    open(os.path.join(build_dir, 'INSTALL-MODE.txt'), 'w').write(
        'Installed RootDetector; per-user data is stored under LOCALAPPDATA.\n'
    )
shutil.rmtree('./build')
os.remove('./main.spec')

if args.prune_torchlibs:
    print('Removing PyTorch binaries...')
    shutil.rmtree(build_dir+'/main/torch/lib')
elif sys.platform == 'win32' and not args.installer_payload:
    import torch
    variant = 'cu113' if torch.version.cuda == '11.3' else 'cpu'
    write_runtime_manifest(os.path.join(build_dir, 'main', 'torch', 'lib'), variant)


# Build both archives locally; the workflow publishes only the full portable ZIP.
if args.zip:
    shutil.rmtree(build_dir+'/cache', ignore_errors=True)

    print('Zipping update package...')
    files_to_zip  = []
    files_to_zip += [os.path.join(build_dir, 'main', 'main.exe')]
    files_to_zip += glob.glob(os.path.join(build_dir, 'static/**'), recursive=True)
    with zipfile.ZipFile(build_dir+'.update.zip', 'w') as archive:
        for f in files_to_zip:
            archive.write(f, f.replace(build_dir, ''))

    print('Zipping full package...')
    shutil.make_archive(build_dir, "zip", build_dir)
    if sys.platform == 'win32':
        with zipfile.ZipFile(build_dir + '.zip') as archive:
            launchers = {
                name for name in archive.namelist()
                if '/' not in name and name.lower().endswith('.bat')
            }
        if launchers != {'StartRootDetector.bat'}:
            raise RuntimeError('Portable ZIP must contain only StartRootDetector.bat.')


print('Done')
