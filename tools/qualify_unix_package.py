"""Install, replace and remove a built Unix package inside an isolated temporary directory.

macOS copies the actual mounted DMG application; Linux extracts the actual AppImage.
This qualifies package installation/repair, not migration from an older release or system services.
"""
import argparse
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile


def checked(arguments, **kwargs):
    return subprocess.run(arguments, check=True, timeout=1200, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    package = args.package.resolve(strict=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform not in ('darwin', 'linux'):
        parser.error('Only macOS and Linux packages are supported')
    with tempfile.TemporaryDirectory(prefix='anonimato-package-qualification-') as directory:
        root = Path(directory)
        installed = root / 'application'
        marker = root / 'fictitious-profile-marker.txt'
        environment = dict(os.environ, ANONIMATO_CPU='1', QT_QPA_PLATFORM='offscreen', XDG_DATA_HOME=str(root / 'profile'))
        for stage in ('install', 'replace'):
            if installed.exists():
                shutil.rmtree(installed)
            if sys.platform == 'darwin':
                mounted = plistlib.loads(checked(['hdiutil', 'attach', '-readonly', '-nobrowse', '-plist', str(package)],
                                                capture_output=True).stdout)
                mount = next(Path(entity['mount-point']) for entity in mounted['system-entities'] if 'mount-point' in entity)
                try:
                    checked(['ditto', str(mount / 'Privelto.app'), str(installed / 'Privelto.app')])
                finally:
                    checked(['hdiutil', 'detach', str(mount)])
                binary = installed / 'Privelto.app/Contents/MacOS/Privelto'
            else:
                installed.mkdir()
                checked([str(package), '--appimage-extract'], cwd=installed, stdout=subprocess.DEVNULL)
                binary = installed / 'squashfs-root/AppRun'
            if stage == 'replace':
                assert marker.read_text('utf-8') == 'fictitious data', 'Replacement removed preserved external profile marker'
            report = args.output.resolve().with_name(f'{args.output.stem}-{stage}.json')
            checked([str(binary), f'--selftest={report}'], env=environment)
            assert report.exists(), 'Installed binary produced no self-test report'
            result = json.loads(report.read_text('utf-8'))
            assert all(result.get(key) is True for key in ('ok', 'integrity', 'crash_recovery')), result
            marker.write_text('fictitious data', encoding='utf-8')
        shutil.rmtree(installed)
        assert not installed.exists(), 'Uninstall left application files behind'
    args.output.write_text(json.dumps({'ok': True, 'platform': sys.platform, 'install': True, 'replace': True,
                                      'remove': True, 'scope': 'Isolated package copy; same-version replacement'}, indent=2) + '\n',
                           encoding='utf-8')


if __name__ == '__main__':
    main()
