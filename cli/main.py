#!/usr/bin/env python3
"""
platform-cli
============
Lets a developer scaffold a production-ready, canary-deployed service
without hand-writing Kubernetes manifests, Argo Rollout specs, or
AnalysisTemplates. Generates GitOps-ready files under gitops/apps/<name>/
that ArgoCD picks up automatically once committed and pushed.
"""
import os
import re
import sys
import argparse
from jinja2 import Template

# Every value below ends up in a filesystem path and in YAML that ArgoCD
# applies with cluster privileges, so it is validated before rendering.
# DNS-1123 labels: what Kubernetes itself accepts for names and namespaces.
DNS1123_LABEL = re.compile(r"^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$")
# registry/repo:tag or registry/repo@sha256:digest, no whitespace or YAML syntax.
IMAGE_REF = re.compile(
    r"^[a-z0-9]+([._-][a-z0-9]+)*(:[0-9]+)?(/[a-z0-9]+([._-][a-z0-9]+)*)*"
    r"(:[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}|@sha256:[a-f0-9]{64})$"
)
REPO_URL = re.compile(r"^https://[A-Za-z0-9.-]+(/[A-Za-z0-9._~-]+)+(\.git)?$")
APPS_ROOT = os.path.join("gitops", "apps")


class ValidationError(ValueError):
    pass


def validate(app_name, environment, image, port, replicas, repo_url):
    if not DNS1123_LABEL.fullmatch(app_name):
        raise ValidationError(f"--name '{app_name}' must be a DNS-1123 label (lowercase letters, digits, '-', max 63 chars)")
    if not DNS1123_LABEL.fullmatch(environment):
        raise ValidationError(f"--env '{environment}' must be a DNS-1123 label")
    if environment in {"kube-system", "kube-public", "kube-node-lease", "argocd", "kyverno", "monitoring"}:
        raise ValidationError(f"--env '{environment}' is a platform namespace; tenant apps cannot deploy there")
    if not IMAGE_REF.fullmatch(image):
        raise ValidationError(f"--image '{image}' must be pinned as repo:tag or repo@sha256:<digest>")
    if image.endswith(":latest"):
        raise ValidationError("--image must not use the ':latest' tag")
    if not 1 <= port <= 65535:
        raise ValidationError(f"--port {port} is outside 1-65535")
    if not 1 <= replicas <= 50:
        raise ValidationError(f"--replicas {replicas} is outside 1-50")
    if not REPO_URL.fullmatch(repo_url):
        raise ValidationError(f"--repo-url '{repo_url}' must be an https:// Git URL")


def safe_target_dir(app_name):
    """Resolve gitops/apps/<name> and refuse anything that escapes it."""
    root = os.path.realpath(APPS_ROOT)
    target = os.path.realpath(os.path.join(root, app_name))
    if os.path.commonpath([root, target]) != root or target == root:
        raise ValidationError(f"--name '{app_name}' resolves outside {APPS_ROOT}/")
    return target

ROLLOUT_TEMPLATE = """\
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: {{ app_name }}
  namespace: {{ environment }}
spec:
  replicas: {{ replicas }}
  strategy:
    canary:
      analysis:
        templates:
          - templateName: success-rate-analysis
        args:
          - name: service-name
            value: {{ app_name }}
      steps:
        - setWeight: 10
        - pause: { duration: 2m }
        - setWeight: 50
        - pause: { duration: 5m }
        - setWeight: 100
  selector:
    matchLabels:
      app: {{ app_name }}
  template:
    metadata:
      labels:
        app: {{ app_name }}
    spec:
      automountServiceAccountToken: false
      securityContext:
        runAsNonRoot: true
        runAsUser: 10001
        runAsGroup: 10001
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: {{ app_name }}
          image: {{ image }}
          ports:
            - containerPort: {{ port }}
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: 500m
              memory: 256Mi
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: ["ALL"]
          volumeMounts:
            - name: tmp
              mountPath: /tmp
      volumes:
        - name: tmp
          emptyDir: {}
---
apiVersion: v1
kind: Service
metadata:
  name: {{ app_name }}
  namespace: {{ environment }}
spec:
  ports:
    - port: {{ port }}
      targetPort: {{ port }}
  selector:
    app: {{ app_name }}
"""

ARGOCD_APP_TEMPLATE = """\
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: {{ app_name }}
  namespace: argocd
spec:
  project: default
  source:
    repoURL: {{ repo_url }}
    targetRevision: main
    path: gitops/apps/{{ app_name }}
  destination:
    server: https://kubernetes.default.svc
    namespace: {{ environment }}
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
"""


def generate_app(app_name, environment, image, port, replicas, repo_url):
    validate(app_name, environment, image, port, replicas, repo_url)
    target_dir = safe_target_dir(app_name)
    os.makedirs(target_dir, exist_ok=True)

    rollout_out = Template(ROLLOUT_TEMPLATE).render(
        app_name=app_name, environment=environment, image=image, port=port, replicas=replicas
    )
    with open(os.path.join(target_dir, "deployment.yaml"), "w", encoding="utf-8") as f:
        f.write(rollout_out.strip() + "\n")

    app_out = Template(ARGOCD_APP_TEMPLATE).render(
        app_name=app_name, environment=environment, repo_url=repo_url
    )
    with open(os.path.join(target_dir, "application.yaml"), "w", encoding="utf-8") as f:
        f.write(app_out.strip() + "\n")

    print(f"[SUCCESS] Scaffolded '{app_name}' at {os.path.relpath(target_dir)}/")
    print(f"          Commit + push, then ArgoCD's App-of-Apps picks it up automatically.")


def main():
    parser = argparse.ArgumentParser(description="Adcash IDP Developer Self-Service CLI")
    subparsers = parser.add_subparsers(dest="command")

    create_parser = subparsers.add_parser("create-app", help="Scaffold a new canary-deployed microservice")
    create_parser.add_argument("--name", required=True)
    create_parser.add_argument("--env", default="staging")
    create_parser.add_argument("--image", required=True)
    create_parser.add_argument("--port", type=int, default=8080)
    create_parser.add_argument("--replicas", type=int, default=3)
    create_parser.add_argument("--repo-url", default="https://github.com/AnirudhBabu/Adcash-Assignment.git")

    args = parser.parse_args()
    if args.command == "create-app":
        try:
            generate_app(args.name, args.env, args.image, args.port, args.replicas, args.repo_url)
        except ValidationError as err:
            sys.exit(f"[ERROR] {err}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
