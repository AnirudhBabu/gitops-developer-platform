"""Security regression tests for platform-cli input handling. Run: pytest cli/"""
import os

import pytest
import yaml

import main

GOOD = dict(
    app_name="payments-service",
    environment="staging",
    image="ghcr.io/anirudhbabu/payments-service:v1.0.0",
    port=8080,
    replicas=3,
    repo_url="https://github.com/AnirudhBabu/gitops-developer-platform.git",
)


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def args(**overrides):
    return {**GOOD, **overrides}


def test_valid_app_is_scaffolded_with_hardened_pod(workdir):
    main.generate_app(**GOOD)
    docs = list(yaml.safe_load_all((workdir / "gitops/apps/payments-service/deployment.yaml").read_text()))
    pod = docs[0]["spec"]["template"]["spec"]
    container = pod["containers"][0]
    assert pod["securityContext"]["runAsNonRoot"] is True
    assert pod["automountServiceAccountToken"] is False
    assert container["securityContext"]["allowPrivilegeEscalation"] is False
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]


@pytest.mark.parametrize(
    "name",
    [
        "../../../escape",        # path traversal out of gitops/apps
        "/etc/cron.d/x",          # absolute path
        "a\n  namespace: kube-system",  # YAML injection
        "payments-service\n",     # trailing newline ($ matches before it)
        "Payments",               # uppercase is not a valid k8s name
        "x" * 64,                 # longer than a DNS-1123 label
        "",
    ],
)
def test_malicious_or_invalid_names_rejected(workdir, name):
    with pytest.raises(main.ValidationError):
        main.generate_app(**args(app_name=name))
    assert not (workdir / "gitops").exists() or not any((workdir / "gitops").rglob("*.yaml"))
    assert not (workdir.parent / "escape").exists()


@pytest.mark.parametrize("env", ["kube-system", "argocd", "kyverno", "monitoring", "staging\n"])
def test_platform_or_invalid_namespaces_rejected(workdir, env):
    with pytest.raises(main.ValidationError):
        main.generate_app(**args(environment=env))


@pytest.mark.parametrize(
    "image",
    [
        "nginx:latest",
        "nginx",                          # unpinned
        "nginx:1\n  privileged: true",    # YAML injection through the image
        "nginx:1 ",                       # whitespace
    ],
)
def test_unpinned_or_malformed_images_rejected(workdir, image):
    with pytest.raises(main.ValidationError):
        main.generate_app(**args(image=image))


def test_digest_pinned_image_accepted(workdir):
    main.generate_app(**args(image="ghcr.io/org/app@sha256:" + "a" * 64))


@pytest.mark.parametrize("port,replicas", [(0, 3), (70000, 3), (8080, 0), (8080, 500)])
def test_numeric_bounds(workdir, port, replicas):
    with pytest.raises(main.ValidationError):
        main.generate_app(**args(port=port, replicas=replicas))


@pytest.mark.parametrize("url", ["http://github.com/a/b.git", "file:///etc/passwd", "https://github.com/a/b.git\nx"])
def test_repo_url_must_be_https(workdir, url):
    with pytest.raises(main.ValidationError):
        main.generate_app(**args(repo_url=url))


def test_symlinked_app_dir_cannot_escape(workdir):
    outside = workdir / "outside"
    outside.mkdir()
    os.makedirs("gitops/apps")
    os.symlink(outside, "gitops/apps/payments-service")
    with pytest.raises(main.ValidationError):
        main.generate_app(**GOOD)
    assert not any(outside.iterdir())
