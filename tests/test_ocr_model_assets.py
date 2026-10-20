"""Model preparation unit tests use byte fixtures and mocked HTTPS, never a real engine."""
import hashlib
import io
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

from install import prepare_ocr_models as assets


@pytest.fixture
def tiny_asset():
    content = b'unit-test-only model bytes; not an ONNX integration fixture'
    return assets.ModelAsset('test.onnx', 'https://models.example/test.onnx',
                             hashlib.sha256(content).hexdigest()), content


def response(data=b'', status=200, location=None):
    result = Mock()
    result.__enter__ = Mock(return_value=result)
    result.__exit__ = Mock(return_value=False)
    result.status_code = status
    result.headers = {'Location': location} if location else {}
    result.iter_content.return_value = [data]
    return result


def test_manifest_matches_required_real_model_set():
    manifest = assets.model_assets()
    assert len(manifest) == 7
    assert {m.name for m in manifest} == {
        'ch_PP-OCRv4_det_mobile.onnx', 'ch_ppocr_mobile_v2.0_cls_mobile.onnx',
        'en_PP-OCRv4_rec_mobile.onnx', 'ch_PP-OCRv4_rec_mobile.onnx',
        'japan_PP-OCRv4_rec_mobile.onnx', 'korean_PP-OCRv4_rec_mobile.onnx',
        'chinese_cht_PP-OCRv3_rec_mobile.onnx'}
    assert all(m.url.startswith('https://www.modelscope.cn/') for m in manifest)
    assert all(len(bytes.fromhex(m.sha256)) == 32 for m in manifest)


def test_missing_assets_are_not_skipped_or_downloaded(tmp_path, monkeypatch, tiny_asset):
    asset, _ = tiny_asset
    monkeypatch.setattr(assets, 'model_assets', lambda languages: [asset])
    with pytest.raises(assets.OCRModelsUnavailable, match='not skipped'):
        assets.require_cached_models(['en'], tmp_path)


def test_corrupt_asset_fails_preflight(tmp_path, monkeypatch, tiny_asset):
    asset, _ = tiny_asset
    (tmp_path / asset.name).write_bytes(b'wrong')
    monkeypatch.setattr(assets, 'model_assets', lambda languages: [asset])
    with pytest.raises(assets.OCRModelsUnavailable, match='SHA256 mismatch'):
        assets.require_cached_models(['en'], tmp_path)


def test_verified_local_bundle_needs_no_network(tmp_path, monkeypatch, tiny_asset):
    asset, content = tiny_asset
    source, target = tmp_path / 'source', tmp_path / 'cache'
    source.mkdir()
    (source / asset.name).write_bytes(content)
    get = Mock(side_effect=AssertionError('network must not be used'))
    assets.prepare_asset(asset, target, source_dir=source, get=get)
    monkeypatch.setattr(assets, 'model_assets', lambda languages: [asset])
    assets.require_cached_models(['en'], target)
    get.assert_not_called()


def test_download_is_explicit_opt_in(tmp_path, tiny_asset):
    asset, _ = tiny_asset
    get = Mock()
    with pytest.raises(assets.OCRModelsUnavailable, match='not prepared'):
        assets.prepare_asset(asset, tmp_path, get=get)
    get.assert_not_called()


def test_mocked_https_verifies_tls_and_checksum(tmp_path, tiny_asset):
    asset, content = tiny_asset
    get = Mock(return_value=response(content))
    assets.prepare_asset(asset, tmp_path, download=True, get=get)
    assert (tmp_path / asset.name).read_bytes() == content
    get.assert_called_once_with(asset.url, stream=True, timeout=(10, 60),
                                verify=True, allow_redirects=False)


@pytest.mark.parametrize('mode', ['download', 'local'])
def test_bad_checksum_does_not_replace_cache(tmp_path, tiny_asset, mode):
    asset, _ = tiny_asset
    old = tmp_path / asset.name
    old.write_bytes(b'previous cache')
    source = tmp_path / 'source'
    source.mkdir()
    (source / asset.name).write_bytes(b'corrupt source')
    with pytest.raises(ValueError, match='SHA256 mismatch'):
        assets.prepare_asset(asset, tmp_path, source_dir=source if mode == 'local' else None,
                             download=mode == 'download', get=Mock(return_value=response(b'corrupt')))
    assert old.read_bytes() == b'previous cache'
    assert not list(tmp_path.glob('.ocr-model-*'))


def test_http_downgrade_is_rejected():
    get = Mock(return_value=response(status=302, location='http://insecure.example/model'))
    with pytest.raises(ValueError, match='HTTPS'):
        assets._copy_https('https://models.example/model', io.BytesIO(), get=get)
    assert get.call_count == 1


def test_https_redirect_retains_tls_verification():
    get = Mock(side_effect=[response(status=302, location='https://cdn.example/model'), response(b'ok')])
    output = io.BytesIO()
    assets._copy_https('https://models.example/model', output, get=get)
    assert output.getvalue() == b'ok'
    assert all(call.kwargs['verify'] is True and call.kwargs['allow_redirects'] is False
               for call in get.call_args_list)


def test_403_preserves_failure_and_cleans_staging(tmp_path, tiny_asset):
    asset, _ = tiny_asset
    denied = response(status=403)
    denied.raise_for_status.side_effect = requests.HTTPError('403 Forbidden')
    with pytest.raises(requests.HTTPError, match='403'):
        assets.prepare_asset(asset, tmp_path, download=True, get=Mock(return_value=denied))
    assert not list(tmp_path.iterdir())


def test_cache_is_reused_without_network(tmp_path, tiny_asset):
    asset, content = tiny_asset
    (tmp_path / asset.name).write_bytes(content)
    get = Mock()
    assets.prepare_asset(asset, tmp_path, download=True, get=get)
    get.assert_not_called()


def test_bear_parser_orchestration_uses_mocked_ocr(monkeypatch):
    import harness
    # This tests the parser boundary, not real PNG recognition accuracy.
    monkeypatch.setattr(harness, '_ocr_bytes_sync', lambda image, lang: 'no player rows')
    result = harness.run_ocr_pipeline(b'mocked image', primary_lang='en', roster=[])
    assert result['rows'] == []
