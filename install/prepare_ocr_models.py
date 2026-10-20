"""Prepare verified RapidOCR 3.8 model assets before running offline OCR tests.

No network is used unless --download is explicitly supplied. Model URLs and
SHA256 digests come from the installed RapidOCR package, not a new mirror.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import tempfile
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import requests
import yaml

LANGUAGES = ('en', 'ch', 'japan', 'korean', 'chinese_cht')


class OCRModelsUnavailable(RuntimeError):
    """Real image inference could not start; this is never a passing result."""


@dataclass(frozen=True)
class ModelAsset:
    name: str
    url: str
    sha256: str


def package_root() -> Path:
    spec = importlib.util.find_spec('rapidocr')
    if spec is None or spec.origin is None:
        raise OCRModelsUnavailable('RapidOCR is not installed; install requirements.txt first')
    return Path(spec.origin).parent


def model_assets(languages=LANGUAGES) -> list[ModelAsset]:
    unknown = set(languages) - set(LANGUAGES)
    if unknown:
        raise ValueError(f'Unsupported OCR fixture languages: {sorted(unknown)}')
    metadata = yaml.safe_load((package_root() / 'default_models.yaml').read_text())
    models = metadata['onnxruntime']['PP-OCRv4']
    entries = [models['det']['ch_PP-OCRv4_det_mobile'],
               models['cls']['ch_ppocr_mobile_v2.0_cls_mobile']]
    for lang in dict.fromkeys(languages):
        matches = [value for name, value in models['rec'].items()
                   if name.startswith(lang + '_') and name.endswith('_mobile')]
        if len(matches) != 1:
            raise ValueError(f'Ambiguous or missing PP-OCRv4 mobile model for {lang}')
        entries.append(matches[0])
    result = []
    for entry in entries:
        url, digest = entry['model_dir'], entry['SHA256']
        if urlsplit(url).scheme != 'https' or len(digest) != 64:
            raise ValueError('Model metadata must contain HTTPS and a SHA256 digest')
        result.append(ModelAsset(Path(urlsplit(url).path).name, url, digest))
    return result


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def asset_problem(asset: ModelAsset, directory: Path) -> str | None:
    path = directory / asset.name
    if not path.is_file():
        return 'missing'
    return None if file_digest(path) == asset.sha256 else 'SHA256 mismatch'


def require_cached_models(languages=LANGUAGES, directory=None) -> None:
    directory = Path(directory) if directory is not None else package_root() / 'models'
    problems = [f'{asset.name}: {problem}' for asset in model_assets(languages)
                if (problem := asset_problem(asset, directory))]
    if problems:
        raise OCRModelsUnavailable(
            'OCR inference unavailable (not skipped): ' + '; '.join(problems)
            + '. Prepare verified assets BEFORE pytest with '
            '`python install/prepare_ocr_models.py --download`, or import an offline '
            'bundle with `--source-dir PATH`. Do not disable TLS or the test network guard.'
        )


def _copy_https(url: str, output, get=requests.get) -> None:
    for _ in range(6):
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Only authenticated-by-TLS HTTPS model downloads are allowed')
        with get(url, stream=True, timeout=(10, 60), verify=True, allow_redirects=False) as response:
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get('Location')
                if not location:
                    raise ValueError('Model redirect has no Location')
                url = urljoin(url, location)
                continue
            response.raise_for_status()
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    output.write(chunk)
            return
    raise ValueError('Too many model redirects')


def prepare_asset(asset: ModelAsset, directory: Path, *, source_dir=None, download=False, get=requests.get):
    if asset_problem(asset, directory) is None:
        return
    if source_dir is None and not download:
        raise OCRModelsUnavailable(f'{asset.name}: not prepared; use --download or --source-dir')
    directory.mkdir(parents=True, exist_ok=True)
    # Verify a separate staging file before replacing any existing cache entry.
    fd, staging_name = tempfile.mkstemp(prefix='.ocr-model-', dir=directory)
    staging = Path(staging_name)
    try:
        with os.fdopen(fd, 'wb') as output:
            if source_dir is not None:
                with (Path(source_dir) / asset.name).open('rb') as source:
                    shutil.copyfileobj(source, output)
            else:
                _copy_https(asset.url, output, get=get)
        if file_digest(staging) != asset.sha256:
            raise ValueError(f'{asset.name}: SHA256 mismatch; cache was not replaced')
        staging.replace(directory / asset.name)
    finally:
        staging.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--download', action='store_true', help='explicitly allow HTTPS asset preparation')
    source.add_argument('--source-dir', type=Path, help='import a local model bundle with SHA256 verification')
    args = parser.parse_args()
    directory = package_root() / 'models'
    try:
        for asset in model_assets():
            prepare_asset(asset, directory, source_dir=args.source_dir, download=args.download)
            print(f'verified: {asset.name} {asset.sha256}')
        require_cached_models(directory=directory)
    except (OCRModelsUnavailable, ValueError, OSError, requests.RequestException) as exc:
        parser.exit(1, f'OCR assets unavailable: {exc}\n')


if __name__ == '__main__':
    main()
