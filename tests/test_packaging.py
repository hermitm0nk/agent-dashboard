from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_python_build_backend_bundles_vite_output():
    pyproject = (ROOT / "pyproject.toml").read_text()
    manifest = (ROOT / "MANIFEST.in").read_text()
    backend = (ROOT / "build_backend.py").read_text()

    assert 'build-backend = "build_backend"' in pyproject
    assert '"web_dist/*"' in pyproject
    assert "recursive-include frontend" in manifest
    assert 'subprocess.run([npm, "ci"]' in backend
    assert 'subprocess.run([npm, "run", "build"]' in backend
