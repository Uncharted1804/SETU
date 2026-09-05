import json
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from backend.app.config import ModelRegistry
from backend.app.contracts import ModelEntry
from backend.app.security.integrity import verify_installed, annotate, load_allowlist


def test_integrity_verified():
    with tempfile.TemporaryDirectory() as td:
        repo_root = Path(td)
        config_dir = repo_root / "config"
        config_dir.mkdir()
        
        allowlist_path = config_dir / "model_allowlist.json"
        
        ollama_home = repo_root / ".ollama"
        manifest_dir = ollama_home / "models" / "manifests" / "registry.ollama.ai" / "library" / "testmodel"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_file = manifest_dir / "latest"
        
        manifest_content = b'{"schemaVersion": 2, "mediaType": "application/vnd.docker.distribution.manifest.v2+json", "config": {}, "layers": []}'
        manifest_file.write_bytes(manifest_content)
        
        import hashlib
        actual_digest = "sha256:" + hashlib.sha256(manifest_content).hexdigest()
        
        allowlist_data = {
            "models": [
                {
                    "model": "testmodel:latest",
                    "manifest_path": "manifests/registry.ollama.ai/library/testmodel/latest",
                    "manifest_sha256": actual_digest.replace("sha256:", "")
                }
            ]
        }
        allowlist_path.write_text(json.dumps(allowlist_data))
        
        entry = ModelEntry(
            id="test-model",
            model="testmodel:latest",
            expected_manifest_digest=actual_digest
        )
        registry = ModelRegistry(entries=[entry], defaults={})
        
        with mock.patch("backend.app.security.integrity.allowlist_path", return_value=allowlist_path):
            results = verify_installed(registry, ollama_home=ollama_home)
            assert results["test-model"] == "VERIFIED"
            
            with mock.patch("backend.app.security.integrity.verify_installed", return_value={"test-model": "VERIFIED"}):
                annotated = annotate(registry, checked=True)
                assert annotated[0].integrity_verified is True


def test_integrity_mismatch():
    with tempfile.TemporaryDirectory() as td:
        repo_root = Path(td)
        config_dir = repo_root / "config"
        config_dir.mkdir()
        allowlist_path = config_dir / "model_allowlist.json"
        
        ollama_home = repo_root / ".ollama"
        manifest_dir = ollama_home / "models" / "manifests" / "registry.ollama.ai" / "library" / "testmodel"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_file = manifest_dir / "latest"
        
        manifest_content = b'{"schemaVersion": 2, "changed": true}'
        manifest_file.write_bytes(manifest_content)
        
        import hashlib
        actual_digest = "sha256:" + hashlib.sha256(manifest_content).hexdigest()
        
        allowlist_data = {
            "models": [
                {
                    "model": "testmodel:latest",
                    "manifest_path": "manifests/registry.ollama.ai/library/testmodel/latest",
                    "manifest_sha256": "wrong_digest"
                }
            ]
        }
        allowlist_path.write_text(json.dumps(allowlist_data))
        
        entry = ModelEntry(
            id="test-model",
            model="testmodel:latest",
            expected_manifest_digest="sha256:wrong_digest"
        )
        registry = ModelRegistry(entries=[entry], defaults={})
        
        with mock.patch("backend.app.security.integrity.allowlist_path", return_value=allowlist_path):
            results = verify_installed(registry, ollama_home=ollama_home)
            assert results["test-model"] == "MISMATCH"
            
            with mock.patch("backend.app.security.integrity.verify_installed", return_value={"test-model": "MISMATCH"}):
                annotated = annotate(registry, checked=True)
                assert annotated[0].integrity_verified is False


def test_integrity_unavailable_no_manifest():
    with tempfile.TemporaryDirectory() as td:
        repo_root = Path(td)
        config_dir = repo_root / "config"
        config_dir.mkdir()
        allowlist_path = config_dir / "model_allowlist.json"
        
        ollama_home = repo_root / ".ollama"
        
        allowlist_data = {
            "models": [
                {
                    "model": "testmodel:latest",
                    "manifest_path": "manifests/registry.ollama.ai/library/testmodel/latest",
                    "manifest_sha256": "some_digest"
                }
            ]
        }
        allowlist_path.write_text(json.dumps(allowlist_data))
        
        entry = ModelEntry(
            id="test-model",
            model="testmodel:latest",
            expected_manifest_digest="sha256:some_digest"
        )
        registry = ModelRegistry(entries=[entry], defaults={})
        
        with mock.patch("backend.app.security.integrity.allowlist_path", return_value=allowlist_path):
            results = verify_installed(registry, ollama_home=ollama_home)
            assert results["test-model"] == "UNAVAILABLE"
            
            with mock.patch("backend.app.security.integrity.verify_installed", return_value={"test-model": "UNAVAILABLE"}):
                annotated = annotate(registry, checked=True)
                assert annotated[0].integrity_verified is None


def test_integrity_multiple():
    with tempfile.TemporaryDirectory() as td:
        repo_root = Path(td)
        config_dir = repo_root / "config"
        config_dir.mkdir()
        allowlist_path = config_dir / "model_allowlist.json"
        
        ollama_home = repo_root / ".ollama"
        
        # M1: VERIFIED
        m1_dir = ollama_home / "models" / "manifests" / "registry.ollama.ai" / "library" / "m1"
        m1_dir.mkdir(parents=True, exist_ok=True)
        m1_file = m1_dir / "latest"
        m1_content = b"m1"
        m1_file.write_bytes(m1_content)
        import hashlib
        m1_digest = "sha256:" + hashlib.sha256(m1_content).hexdigest()
        
        # M2: MISMATCH
        m2_dir = ollama_home / "models" / "manifests" / "registry.ollama.ai" / "library" / "m2"
        m2_dir.mkdir(parents=True, exist_ok=True)
        m2_file = m2_dir / "latest"
        m2_file.write_bytes(b"wrong content")
        
        # M3: UNAVAILABLE
        
        allowlist_data = {
            "models": [
                {
                    "model": "m1:latest",
                    "manifest_path": "manifests/registry.ollama.ai/library/m1/latest",
                    "manifest_sha256": m1_digest.replace("sha256:", "")
                },
                {
                    "model": "m2:latest",
                    "manifest_path": "manifests/registry.ollama.ai/library/m2/latest",
                    "manifest_sha256": "expected_m2_digest"
                },
                {
                    "model": "m3:latest",
                    "manifest_path": "manifests/registry.ollama.ai/library/m3/latest",
                    "manifest_sha256": "expected_m3_digest"
                }
            ]
        }
        allowlist_path.write_text(json.dumps(allowlist_data))
        
        e1 = ModelEntry(id="m1", model="m1:latest", expected_manifest_digest=m1_digest)
        e2 = ModelEntry(id="m2", model="m2:latest", expected_manifest_digest="sha256:expected_m2_digest")
        e3 = ModelEntry(id="m3", model="m3:latest", expected_manifest_digest="sha256:expected_m3_digest")
        registry = ModelRegistry(entries=[e1, e2, e3], defaults={})
        
        with mock.patch("backend.app.security.integrity.allowlist_path", return_value=allowlist_path):
            results = verify_installed(registry, ollama_home=ollama_home)
            assert results["m1"] == "VERIFIED"
            assert results["m2"] == "MISMATCH"
            assert results["m3"] == "UNAVAILABLE"
