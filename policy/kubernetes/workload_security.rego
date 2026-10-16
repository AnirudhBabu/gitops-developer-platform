# Workload hardening policies, evaluated with Conftest (OPA) in CI.
#
# Why custom Rego: Checkov and similar scanners only recognise built-in
# workload kinds, so an Argo Rollout's pod template is never inspected.
# These rules resolve the pod spec for every workload kind, Rollout
# included, so canary-deployed services get the same scrutiny as a Deployment.
package main

import rego.v1

workload_kinds := {"Deployment", "StatefulSet", "DaemonSet", "ReplicaSet", "Job", "Rollout"}

pod_spec := input.spec if input.kind == "Pod"

pod_spec := input.spec.template.spec if workload_kinds[input.kind]

pod_spec := input.spec.jobTemplate.spec.template.spec if input.kind == "CronJob"

containers contains c if some c in pod_spec.containers

containers contains c if some c in pod_spec.initContainers

name := sprintf("%s/%s", [input.kind, input.metadata.name])

# Field lookups go through object.get with explicit defaults. A bare
# `not <path>` over a missing field is undefined in Rego, so the rule body
# silently fails and the violation is never reported.
container_sc(c, field) := object.get(c, ["securityContext", field], null)

pod_sc(field) := object.get(pod_spec, ["securityContext", field], null)

# Container-level securityContext wins over the pod-level one.
effective(c, field) := container_sc(c, field) if container_sc(c, field) != null

effective(c, field) := pod_sc(field) if container_sc(c, field) == null

# --- Image provenance ---------------------------------------------------

deny contains msg if {
	some c in containers
	not contains(c.image, ":")
	not contains(c.image, "@sha256:")
	msg := sprintf("%s: container '%s' image '%s' has no tag; pin a version or digest", [name, c.name, c.image])
}

deny contains msg if {
	some c in containers
	endswith(c.image, ":latest")
	msg := sprintf("%s: container '%s' uses ':latest'; pin a version or digest", [name, c.name])
}

# --- Privilege ----------------------------------------------------------

deny contains msg if {
	some c in containers
	container_sc(c, "privileged") == true
	msg := sprintf("%s: container '%s' runs privileged", [name, c.name])
}

deny contains msg if {
	some c in containers
	effective(c, "allowPrivilegeEscalation") != false
	msg := sprintf("%s: container '%s' must set allowPrivilegeEscalation: false", [name, c.name])
}

deny contains msg if {
	some c in containers
	effective(c, "runAsNonRoot") != true
	msg := sprintf("%s: container '%s' must set runAsNonRoot: true", [name, c.name])
}

deny contains msg if {
	some c in containers
	drops := object.get(c, ["securityContext", "capabilities", "drop"], [])
	not "ALL" in drops
	msg := sprintf("%s: container '%s' must drop ALL Linux capabilities", [name, c.name])
}

deny contains msg if {
	some c in containers
	effective(c, "readOnlyRootFilesystem") != true
	msg := sprintf("%s: container '%s' must set readOnlyRootFilesystem: true", [name, c.name])
}

# --- Host isolation -----------------------------------------------------

deny contains msg if {
	some field in ["hostNetwork", "hostPID", "hostIPC"]
	object.get(pod_spec, field, false) == true
	msg := sprintf("%s: %s is not allowed", [name, field])
}

deny contains msg if {
	some v in pod_spec.volumes
	v.hostPath
	msg := sprintf("%s: hostPath volume '%s' is not allowed", [name, v.name])
}

# --- Resource governance (mirrors the Kyverno admission policy) -------------

deny contains msg if {
	some c in containers
	some kind in ["requests", "limits"]
	some res in ["cpu", "memory"]
	object.get(c, ["resources", kind, res], null) == null
	msg := sprintf("%s: container '%s' is missing resources.%s.%s", [name, c.name, kind, res])
}

# --- Defence in depth (warnings, do not fail the build) -----------------

warn contains msg if {
	object.get(pod_spec, "automountServiceAccountToken", true) != false
	msg := sprintf("%s: consider automountServiceAccountToken: false unless the app calls the Kubernetes API", [name])
}

warn contains msg if {
	object.get(pod_spec, ["securityContext", "seccompProfile", "type"], null) == null
	msg := sprintf("%s: consider seccompProfile.type: RuntimeDefault", [name])
}
