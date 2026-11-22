"""Build a source distribution from an explicit allowlist; never include user setup or secrets."""
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parents[1]
# Internal planning/review notes stay in the repository only (docs/reference/PRIVACY-RELEASE.md).
INTERNAL = {
    'docs/reference/PLAN.md',
    'docs/reference/SCENARIO-REVIEW.md',
    'docs/reference/RELIABILITY-REVIEW.md',
    'docs/reference/WIZARD-FIELD-AUDIT.md',
}
files = [
    'README.md',
    'LICENSE',
    'outbound.py',
    'wizard.html',
    'setup.example.json',
    '시작하기.command',
    '시작하기.bat',
]
# Core modular source tree and helper scripts
for folder in ('src', 'scripts'):
    files.extend(
        str(p.relative_to(root)) for p in (root / folder).rglob('*')
        if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'
    )
# pack/ is a curated skill & preset tree: ship every file (scripts, data, third-party LICENSE files).
files.extend(
    str(p.relative_to(root)) for p in (root / 'pack').rglob('*')
    if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'
)
for folder in ('docs', 'agent-skill', 'samples'):
    files.extend(
        str(p.relative_to(root)) for p in (root / folder).rglob('*')
        if p.is_file() and (p.suffix in ('.md', '.json', '.py', '.csv')
                            or (folder == 'samples' and p.suffix == '.html'))
        and 'archive' not in p.parts and 'assets' not in p.parts
        and '.build-v2' not in p.parts and 'output' not in p.parts
    )
target = root / 'dist/hermes-outbound-kit-0.1.zip'
target.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
    for name in sorted(set(files) - INTERNAL):
        archive.write(root / name, 'hermes-outbound-kit/' + name)
print(target)
