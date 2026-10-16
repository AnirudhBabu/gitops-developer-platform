# Unit tests for workload_security.rego. Run with: conftest verify --policy policy/kubernetes
package main

import rego.v1

hardened_container := {
	"name": "app",
	"image": "ghcr.io/example/app:v1.2.3",
	"resources": {
		"requests": {"cpu": "100m", "memory": "128Mi"},
		"limits": {"cpu": "500m", "memory": "256Mi"},
	},
	"securityContext": {
		"allowPrivilegeEscalation": false,
		"readOnlyRootFilesystem": true,
		"capabilities": {"drop": ["ALL"]},
	},
}

rollout(container, pod_extra) := {
	"kind": "Rollout",
	"metadata": {"name": "svc"},
	"spec": {"template": {"spec": object.union(
		{
			"automountServiceAccountToken": false,
			"securityContext": {"runAsNonRoot": true, "seccompProfile": {"type": "RuntimeDefault"}},
			"containers": [container],
		},
		pod_extra,
	)}},
}

test_hardened_rollout_passes if {
	count(deny) == 0 with input as rollout(hardened_container, {})
	count(warn) == 0 with input as rollout(hardened_container, {})
}

test_bare_container_reports_every_gap if {
	bare := {"name": "app", "image": "nginx:latest"}
	result := deny with input as {"kind": "Rollout", "metadata": {"name": "svc"}, "spec": {"template": {"spec": {"containers": [bare]}}}}

	# latest tag, escalation, non-root, caps, read-only root fs, 4 missing resources
	count(result) == 9
}

test_untagged_image_denied if {
	c := object.union(hardened_container, {"image": "nginx"})
	some msg in deny with input as rollout(c, {})
	contains(msg, "has no tag")
}

test_digest_pinned_image_allowed if {
	c := object.union(hardened_container, {"image": "nginx@sha256:0123abcd"})
	count(deny) == 0 with input as rollout(c, {})
}

test_privileged_denied if {
	c := object.union(hardened_container, {"securityContext": object.union(hardened_container.securityContext, {"privileged": true})})
	some msg in deny with input as rollout(c, {})
	contains(msg, "runs privileged")
}

test_container_overrides_pod_run_as_non_root if {
	c := object.union(hardened_container, {"securityContext": object.union(hardened_container.securityContext, {"runAsNonRoot": false})})
	some msg in deny with input as rollout(c, {})
	contains(msg, "runAsNonRoot")
}

test_host_network_denied if {
	some msg in deny with input as rollout(hardened_container, {"hostNetwork": true})
	contains(msg, "hostNetwork")
}

test_host_path_denied if {
	some msg in deny with input as rollout(hardened_container, {"volumes": [{"name": "docker", "hostPath": {"path": "/var/run/docker.sock"}}]})
	contains(msg, "hostPath")
}

test_cronjob_pod_spec_is_resolved if {
	bad := {"name": "job", "image": "busybox:latest"}
	cron := {"kind": "CronJob", "metadata": {"name": "nightly"}, "spec": {"jobTemplate": {"spec": {"template": {"spec": {"containers": [bad]}}}}}}
	some msg in deny with input as cron
	contains(msg, "CronJob/nightly")
}

test_non_workload_kinds_ignored if {
	count(deny) == 0 with input as {"kind": "Service", "metadata": {"name": "svc"}, "spec": {"ports": [{"port": 80}]}}
}
