{{/*
_helpers.tpl - the ONLY place names, labels, images, capability guards,
security contexts, model staging and shared env are defined. Templates compose
these; they never re-derive them.
*/}}

{{/* ------------------------------------------------------------------ names */}}

{{- define "hansard.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "hansard.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "hansard.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "hansard.namespace" -}}
{{- default .Release.Namespace .Values.namespaceOverride -}}
{{- end -}}

{{/* component-scoped resource name: (dict "ctx" . "component" "worker-cpu") */}}
{{- define "hansard.componentName" -}}
{{- printf "%s-%s" (include "hansard.fullname" .ctx) .component | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* ----------------------------------------------------------------- labels */}}

{{- define "hansard.selectorLabels" -}}
app.kubernetes.io/name: {{ include "hansard.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "hansard.labels" -}}
helm.sh/chart: {{ include "hansard.chart" . }}
{{ include "hansard.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: hansard
{{- with .Values.commonLabels }}
{{ toYaml . }}
{{- end }}
{{- end -}}

{{/* (dict "ctx" . "component" "orchestrator") */}}
{{- define "hansard.componentLabels" -}}
{{ include "hansard.labels" .ctx }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{- define "hansard.componentSelectorLabels" -}}
{{ include "hansard.selectorLabels" .ctx }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{- define "hansard.annotations" -}}
{{- with .Values.commonAnnotations }}
{{ toYaml . }}
{{- end }}
{{- end -}}

{{/* ----------------------------------------------------------------- images */}}

{{/* (dict "ctx" . "image" .Values.images.api) -> registry/repo@digest or repo:tag */}}
{{- define "hansard.image" -}}
{{- $ctx := .ctx -}}
{{- $image := .image -}}
{{- $registry := $image.registry | default $ctx.Values.global.imageRegistry -}}
{{- $ref := "" -}}
{{- if $image.digest -}}
{{- $ref = printf "%s@%s" $image.repository $image.digest -}}
{{- else -}}
{{- $ref = printf "%s:%s" $image.repository ($image.tag | default $ctx.Chart.AppVersion) -}}
{{- end -}}
{{- if $registry -}}
{{- printf "%s/%s" (trimSuffix "/" $registry) $ref -}}
{{- else -}}
{{- $ref -}}
{{- end -}}
{{- end -}}

{{- define "hansard.imagePullSecrets" -}}
{{- with .Values.global.imagePullSecrets }}
imagePullSecrets:
{{ toYaml . }}
{{- end }}
{{- end -}}

{{/* ------------------------------------------------------ capability guards */}}

{{/* (dict "ctx" . "apiVersion" "monitoring.coreos.com/v1") -> "true" | "" */}}
{{- define "hansard.hasCRD" -}}
{{- if .ctx.Capabilities.APIVersions.Has .apiVersion -}}true{{- end -}}
{{- end -}}

{{/*
Tri-state resolver. (dict "ctx" . "value" <bool|"auto"> "apiVersion" "<gv>")
  true  -> always emit (operator asserts the CRD exists)
  false -> never emit
  auto  -> emit only when the CRD is present in the target cluster
`helm template` without --api-versions sees builtin groups only, which is
exactly the NKP Starter simulation: every `auto` integration disappears.
*/}}
{{- define "hansard.enabled" -}}
{{- $value := .value -}}
{{- if kindIs "bool" $value -}}
{{- if $value -}}true{{- end -}}
{{- else if eq (lower (toString $value)) "auto" -}}
{{- include "hansard.hasCRD" (dict "ctx" .ctx "apiVersion" .apiVersion) -}}
{{- else if eq (lower (toString $value)) "true" -}}
true
{{- end -}}
{{- end -}}

{{- define "hansard.capabilities.serviceMonitor" -}}
{{- include "hansard.enabled" (dict "ctx" . "value" .Values.metrics.serviceMonitor.enabled "apiVersion" "monitoring.coreos.com/v1") -}}
{{- end -}}

{{- define "hansard.capabilities.prometheusRule" -}}
{{- include "hansard.enabled" (dict "ctx" . "value" .Values.metrics.prometheusRule.enabled "apiVersion" "monitoring.coreos.com/v1") -}}
{{- end -}}

{{/* The Grafana sidecar consumes a plain ConfigMap, so the honest probe for
     "is there a Grafana" is the presence of the Prometheus operator CRDs that
     ship in the same kube-prometheus-stack. */}}
{{- define "hansard.capabilities.grafanaDashboard" -}}
{{- include "hansard.enabled" (dict "ctx" . "value" .Values.metrics.grafanaDashboard.enabled "apiVersion" "monitoring.coreos.com/v1") -}}
{{- end -}}

{{- define "hansard.capabilities.externalSecret" -}}
{{- include "hansard.enabled" (dict "ctx" . "value" .Values.secrets.externalSecret.enabled "apiVersion" "external-secrets.io/v1beta1") -}}
{{- end -}}

{{- define "hansard.capabilities.keda" -}}
{{- include "hansard.enabled" (dict "ctx" . "value" .Values.worker.autoscaling.keda.enabled "apiVersion" "keda.sh/v1alpha1") -}}
{{- end -}}

{{- define "hansard.capabilities.cilium" -}}
{{- include "hansard.enabled" (dict "ctx" . "value" .Values.cilium.networkPolicy.enabled "apiVersion" "cilium.io/v2") -}}
{{- end -}}

{{- define "hansard.capabilities.cosi" -}}
{{- include "hansard.enabled" (dict "ctx" . "value" .Values.storage.cosi.enabled "apiVersion" "objectstorage.k8s.io/v1alpha1") -}}
{{- end -}}

{{- define "hansard.capabilities.volumeSnapshot" -}}
{{- include "hansard.hasCRD" (dict "ctx" . "apiVersion" "snapshot.storage.k8s.io/v1") -}}
{{- end -}}

{{/* ---------------------------------------------------------- compute gates */}}

{{- define "hansard.gpuEnabled" -}}
{{- if or (eq .Values.asr.compute "gpu") (eq .Values.asr.compute "both") -}}true{{- end -}}
{{- end -}}

{{- define "hansard.cpuEnabled" -}}
{{- if or (eq .Values.asr.compute "cpu") (eq .Values.asr.compute "both") (eq .Values.asr.compute "auto") -}}true{{- end -}}
{{- end -}}

{{/* -------------------------------------------------------- service accounts */}}

{{- define "hansard.serviceAccountName.orchestrator" -}}
{{- if .Values.serviceAccounts.orchestrator.create -}}
{{- default (include "hansard.componentName" (dict "ctx" . "component" "orchestrator")) .Values.serviceAccounts.orchestrator.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccounts.orchestrator.name -}}
{{- end -}}
{{- end -}}

{{- define "hansard.serviceAccountName.worker" -}}
{{- if .Values.serviceAccounts.worker.create -}}
{{- default (include "hansard.componentName" (dict "ctx" . "component" "worker")) .Values.serviceAccounts.worker.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccounts.worker.name -}}
{{- end -}}
{{- end -}}

{{- define "hansard.serviceAccountName.bot" -}}
{{- if .Values.serviceAccounts.bot.create -}}
{{- default (include "hansard.componentName" (dict "ctx" . "component" "bot")) .Values.serviceAccounts.bot.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccounts.bot.name -}}
{{- end -}}
{{- end -}}

{{/* ---------------------------------------------------------------- secrets */}}

{{- define "hansard.secretName" -}}
{{- if .Values.secrets.existingSecret -}}
{{- .Values.secrets.existingSecret -}}
{{- else -}}
{{- include "hansard.componentName" (dict "ctx" . "component" "secrets") -}}
{{- end -}}
{{- end -}}

{{/* -------------------------------------------------------- security context */}}

{{- define "hansard.podSecurityContext" -}}
runAsNonRoot: true
runAsUser: {{ .Values.podSecurity.runAsUser }}
runAsGroup: {{ .Values.podSecurity.runAsGroup }}
fsGroup: {{ .Values.podSecurity.fsGroup }}
fsGroupChangePolicy: OnRootMismatch
seccompProfile:
  type: RuntimeDefault
{{- end -}}

{{- define "hansard.containerSecurityContext" -}}
allowPrivilegeEscalation: false
privileged: false
readOnlyRootFilesystem: true
runAsNonRoot: true
runAsUser: {{ .Values.podSecurity.runAsUser }}
runAsGroup: {{ .Values.podSecurity.runAsGroup }}
capabilities:
  drop:
    - ALL
seccompProfile:
  type: RuntimeDefault
{{- end -}}

{{/* --------------------------------------------------- writable scratch dirs */}}
{{/* readOnlyRootFilesystem: true means every writable path is explicit. */}}

{{- define "hansard.scratchVolumes" -}}
- name: tmp
  emptyDir:
    sizeLimit: 1Gi
{{- end -}}

{{- define "hansard.scratchVolumeMounts" -}}
- name: tmp
  mountPath: /tmp
{{- end -}}

{{/* -------------------------------------------------------------- custom CA */}}

{{- define "hansard.ca.volumes" -}}
{{- if and .Values.global.customCA.enabled .Values.global.customCA.existingSecret }}
- name: custom-ca
  secret:
    secretName: {{ .Values.global.customCA.existingSecret }}
    items:
      - key: {{ .Values.global.customCA.key }}
        path: custom-ca.crt
{{- end }}
{{- end -}}

{{- define "hansard.ca.volumeMounts" -}}
{{- if and .Values.global.customCA.enabled .Values.global.customCA.existingSecret }}
- name: custom-ca
  mountPath: /etc/ssl/hansard
  readOnly: true
{{- end }}
{{- end -}}

{{- define "hansard.ca.env" -}}
{{- if and .Values.global.customCA.enabled .Values.global.customCA.existingSecret }}
- name: SSL_CERT_FILE
  value: /etc/ssl/hansard/custom-ca.crt
- name: REQUESTS_CA_BUNDLE
  value: /etc/ssl/hansard/custom-ca.crt
- name: CURL_CA_BUNDLE
  value: /etc/ssl/hansard/custom-ca.crt
- name: NODE_EXTRA_CA_CERTS
  value: /etc/ssl/hansard/custom-ca.crt
- name: AWS_CA_BUNDLE
  value: /etc/ssl/hansard/custom-ca.crt
{{- end }}
{{- end -}}

{{/* ------------------------------------------------------------------ redis */}}

{{- define "hansard.redis.serviceName" -}}
{{- include "hansard.componentName" (dict "ctx" . "component" "redis") -}}
{{- end -}}

{{- define "hansard.redis.url" -}}
{{- if .Values.redis.enabled -}}
{{- printf "redis://%s.%s.svc.cluster.local:%v/0" (include "hansard.redis.serviceName" .) (include "hansard.namespace" .) .Values.redis.port -}}
{{- else -}}
{{- .Values.redis.external.url -}}
{{- end -}}
{{- end -}}

{{/* ------------------------------------------------------------------ proxy */}}

{{- define "hansard.proxyEnv" -}}
{{- $proxy := .Values.networkPolicy.egress.proxy }}
{{- if and (eq .Values.networkPolicy.egress.mode "proxy") $proxy.host }}
- name: HTTPS_PROXY
  value: {{ printf "http://%s:%v" $proxy.host $proxy.port | quote }}
- name: HTTP_PROXY
  value: {{ printf "http://%s:%v" $proxy.host $proxy.port | quote }}
- name: NO_PROXY
  value: {{ $proxy.noProxy | quote }}
{{- end }}
{{- end -}}

{{/* ------------------------------------------------------------------ models */}}

{{- define "hansard.models.volumes" -}}
{{- $models := .Values.models }}
{{- if eq $models.source "pvc" }}
- name: models
  persistentVolumeClaim:
    claimName: {{ $models.pvc.existingClaim | default (include "hansard.componentName" (dict "ctx" . "component" "models")) }}
    readOnly: true
{{- else if eq $models.source "image" }}
{{/* Kubernetes ImageVolume. Beta and disabled by default in 1.33; needs
     containerd >= 2.1. Verified opt-in only. */}}
- name: models
  image:
    reference: {{ include "hansard.image" (dict "ctx" . "image" .Values.images.modelsArtifact) }}
    pullPolicy: {{ .Values.images.modelsArtifact.pullPolicy }}
{{- else }}
- name: models
  emptyDir:
    {{- with $models.emptyDir.medium }}
    medium: {{ . }}
    {{- end }}
    sizeLimit: {{ $models.emptyDir.sizeLimit }}
{{- end }}
{{- end -}}

{{- define "hansard.models.volumeMounts" -}}
- name: models
  mountPath: {{ .Values.models.mountPath }}
  {{- if or (eq .Values.models.source "pvc") (eq .Values.models.source "image") }}
  readOnly: true
  {{- end }}
{{- end -}}

{{/* Init container that stages weights. Nothing is ever fetched by the app. */}}
{{- define "hansard.models.initContainers" -}}
{{- $models := .Values.models }}
{{- if eq $models.source "initImage" }}
- name: stage-models
  image: {{ include "hansard.image" (dict "ctx" . "image" .Values.images.modelsInit) }}
  imagePullPolicy: {{ .Values.images.modelsInit.pullPolicy }}
  env:
    - name: HANSARD_MODELS_TARGET
      value: {{ $models.mountPath | quote }}
  securityContext:
    {{- include "hansard.containerSecurityContext" . | nindent 4 }}
  resources:
    {{- toYaml $models.resources | nindent 4 }}
  volumeMounts:
    - name: models
      mountPath: {{ $models.mountPath }}
{{- else if eq $models.source "oras" }}
- name: stage-models
  image: {{ include "hansard.image" (dict "ctx" . "image" .Values.images.oras) }}
  imagePullPolicy: {{ .Values.images.oras.pullPolicy }}
  command:
    - /bin/sh
    - -ec
    - |
      cd "${HANSARD_MODELS_TARGET}"
      oras pull "${HANSARD_MODELS_REF}" --output . {{ join " " $models.oras.extraArgs }}
      {{- if $models.verifyChecksums }}
      sha256sum -c SHA256SUMS >/dev/null
      {{- end }}
      echo "model artifact staged from ${HANSARD_MODELS_REF}"
  env:
    - name: HANSARD_MODELS_TARGET
      value: {{ $models.mountPath | quote }}
    - name: HANSARD_MODELS_REF
      value: {{ required "models.oras.reference is required when models.source=oras" $models.oras.reference | quote }}
    - name: HOME
      value: /tmp
    {{- include "hansard.ca.env" . | nindent 4 }}
    {{- include "hansard.proxyEnv" . | nindent 4 }}
  securityContext:
    {{- include "hansard.containerSecurityContext" . | nindent 4 }}
  resources:
    {{- toYaml $models.resources | nindent 4 }}
  volumeMounts:
    - name: models
      mountPath: {{ $models.mountPath }}
    {{- include "hansard.scratchVolumeMounts" . | nindent 4 }}
    {{- include "hansard.ca.volumeMounts" . | nindent 4 }}
{{- else if eq $models.source "s3" }}
- name: stage-models
  image: {{ include "hansard.image" (dict "ctx" . "image" .Values.images.s3cli) }}
  imagePullPolicy: {{ .Values.images.s3cli.pullPolicy }}
  command:
    - /bin/sh
    - -ec
    - |
      mc alias set hansard "${HANSARD_S3_ENDPOINT}" "${AWS_ACCESS_KEY_ID}" "${AWS_SECRET_ACCESS_KEY}" --api S3v4
      mc mirror --overwrite "hansard/${HANSARD_S3_BUCKET}/${HANSARD_S3_PREFIX}" "${HANSARD_MODELS_TARGET}"
      {{- if $models.verifyChecksums }}
      cd "${HANSARD_MODELS_TARGET}" && sha256sum -c SHA256SUMS >/dev/null
      {{- end }}
      echo "model artifact staged from ${HANSARD_S3_BUCKET}/${HANSARD_S3_PREFIX}"
  env:
    - name: HANSARD_MODELS_TARGET
      value: {{ $models.mountPath | quote }}
    - name: HANSARD_S3_ENDPOINT
      value: {{ required "models.s3.endpoint is required when models.source=s3" $models.s3.endpoint | quote }}
    - name: HANSARD_S3_BUCKET
      value: {{ required "models.s3.bucket is required when models.source=s3" $models.s3.bucket | quote }}
    - name: HANSARD_S3_PREFIX
      value: {{ $models.s3.prefix | quote }}
    - name: MC_CONFIG_DIR
      value: /tmp/.mc
    - name: HOME
      value: /tmp
    {{- include "hansard.s3CredentialEnv" . | nindent 4 }}
    {{- include "hansard.ca.env" . | nindent 4 }}
    {{- include "hansard.proxyEnv" . | nindent 4 }}
  securityContext:
    {{- include "hansard.containerSecurityContext" . | nindent 4 }}
  resources:
    {{- toYaml $models.resources | nindent 4 }}
  volumeMounts:
    - name: models
      mountPath: {{ $models.mountPath }}
    {{- include "hansard.scratchVolumeMounts" . | nindent 4 }}
    {{- include "hansard.ca.volumeMounts" . | nindent 4 }}
{{- end }}
{{- end -}}

{{/* -------------------------------------------------------- S3 credentials */}}

{{- define "hansard.s3CredentialEnv" -}}
{{- $s3 := .Values.storage.s3 }}
{{- $secret := $s3.credentials.existingSecret | default (include "hansard.secretName" .) }}
- name: AWS_ACCESS_KEY_ID
  valueFrom:
    secretKeyRef:
      name: {{ $secret }}
      key: {{ $s3.credentials.accessKeyKey }}
      optional: true
- name: AWS_SECRET_ACCESS_KEY
  valueFrom:
    secretKeyRef:
      name: {{ $secret }}
      key: {{ $s3.credentials.secretKeyKey }}
      optional: true
{{- end -}}

{{/* --------------------------------------------------------- shared runtime */}}

{{/* Model contract: one mount path, one set of offline switches, everywhere. */}}
{{- define "hansard.models.env" -}}
- name: HANSARD_RUNTIME__MODELS_DIR
  value: {{ .Values.models.mountPath | quote }}
- name: HANSARD_RUNTIME__ALLOW_MODEL_DOWNLOADS
  value: "false"
- name: HF_HOME
  value: {{ printf "%s/.cache" .Values.models.mountPath | quote }}
- name: HF_HUB_OFFLINE
  value: "1"
- name: TRANSFORMERS_OFFLINE
  value: "1"
- name: HF_HUB_DISABLE_TELEMETRY
  value: "1"
{{- end -}}

{{- define "hansard.commonEnv" -}}
- name: HANSARD_RUNTIME__TELEMETRY_ENABLED
  value: "false"
- name: HANSARD_QUEUE_URL
  {{- if and (not .Values.redis.enabled) .Values.redis.external.existingSecret }}
  valueFrom:
    secretKeyRef:
      name: {{ .Values.redis.external.existingSecret }}
      key: {{ .Values.redis.external.existingSecretKey }}
  {{- else }}
  value: {{ include "hansard.redis.url" . | quote }}
  {{- end }}
- name: POD_NAME
  valueFrom:
    fieldRef:
      fieldPath: metadata.name
- name: POD_NAMESPACE
  valueFrom:
    fieldRef:
      fieldPath: metadata.namespace
- name: NODE_NAME
  valueFrom:
    fieldRef:
      fieldPath: spec.nodeName
{{ include "hansard.models.env" . }}
{{- include "hansard.ca.env" . }}
{{- include "hansard.proxyEnv" . }}
{{- end -}}

{{- define "hansard.envFrom" -}}
- configMapRef:
    name: {{ include "hansard.componentName" (dict "ctx" . "component" "config") }}
- secretRef:
    name: {{ include "hansard.secretName" . }}
    optional: true
{{- with .Values.config.extraEnvFrom }}
{{ toYaml . }}
{{- end }}
{{- end -}}

{{/* -------------------------------------------------------------- autoscale */}}

{{/* Emit `replicas:` only when nothing else owns the field. */}}
{{- define "hansard.orchestratorReplicas" -}}
{{- if not .Values.orchestrator.autoscaling.enabled -}}
replicas: {{ .Values.orchestrator.replicaCount }}
{{- end -}}
{{- end -}}

{{/* (dict "ctx" . "component" "worker-cpu" "replicas" 2) */}}
{{- define "hansard.workerReplicas" -}}
{{- $ctx := .ctx -}}
{{- $keda := include "hansard.capabilities.keda" $ctx -}}
{{- $kedaTarget := printf "worker-%s" $ctx.Values.worker.autoscaling.keda.target -}}
{{- $managed := or (and $keda (eq .component $kedaTarget)) (and (not $keda) $ctx.Values.worker.autoscaling.hpa.enabled) -}}
{{- if not $managed -}}
replicas: {{ .replicas }}
{{- end -}}
{{- end -}}

{{/* ------------------------------------------------------------- validation */}}

{{- define "hansard.validate" -}}
{{- $count := 0 -}}
{{- if .Values.secrets.create -}}{{- $count = add1 $count -}}{{- end -}}
{{- if .Values.secrets.existingSecret -}}{{- $count = add1 $count -}}{{- end -}}
{{- if and (not (kindIs "bool" .Values.secrets.externalSecret.enabled)) (eq (lower (toString .Values.secrets.externalSecret.enabled)) "auto") -}}
{{- $count = add1 $count -}}
{{- else if .Values.secrets.externalSecret.enabled -}}
{{- $count = add1 $count -}}
{{- end -}}
{{- if ne $count 1 -}}
{{- fail "set exactly one of secrets.create, secrets.existingSecret or secrets.externalSecret.enabled" -}}
{{- end -}}
{{- if and (not .Values.redis.enabled) (not .Values.redis.external.url) (not .Values.redis.external.existingSecret) -}}
{{- fail "redis.enabled=false requires redis.external.url or redis.external.existingSecret" -}}
{{- end -}}
{{- if and (eq .Values.storage.backend "s3") (not .Values.storage.s3.endpoint) (not (include "hansard.capabilities.cosi" .)) -}}
{{- fail "storage.backend=s3 requires storage.s3.endpoint, or storage.cosi.enabled with the COSI CRDs present" -}}
{{- end -}}
{{- if and (eq .Values.storage.backend "s3") .Values.storage.s3.endpoint (not .Values.storage.s3.forcePathStyle) -}}
{{- fail "storage.s3.forcePathStyle must stay true: Nutanix Objects and every other on-prem S3 gateway require path-style addressing" -}}
{{- end -}}
{{- if and (eq .Values.capture.engine "browser") (not .Values.bot.enabled) -}}
{{- fail "capture.engine=browser requires bot.enabled=true" -}}
{{- end -}}
{{- if and (eq .Values.networkPolicy.egress.mode "proxy") (not .Values.networkPolicy.egress.proxy.host) -}}
{{- fail "networkPolicy.egress.mode=proxy requires networkPolicy.egress.proxy.host" -}}
{{- end -}}
{{- if .Values.global.requireImageDigests -}}
{{- range $name, $image := .Values.images -}}
{{- if not $image.digest -}}
{{- fail (printf "global.requireImageDigests is set but images.%s.digest is empty" $name) -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- if and .Values.webhook.enabled (not .Values.webhook.ingress.enabled) -}}
{{- fail "webhook.enabled requires webhook.ingress.enabled: Microsoft Graph change notifications need a public inbound HTTPS endpoint" -}}
{{- end -}}
{{- end -}}

{{/* ------------------------------------------------------------ worker pods */}}
{{/*
One definition for both worker variants. (dict "ctx" . "variant" "cpu"|"gpu")
The CPU and GPU deployments are identical apart from image, resources,
placement and the GPU device request, so they must not be two files of
copy-pasted YAML: they are one shape rendered twice.
*/}}
{{- define "hansard.worker.deployment" -}}
{{- $ctx := .ctx -}}
{{- $variant := .variant -}}
{{- $component := printf "worker-%s" $variant -}}
{{- $tuning := index $ctx.Values.worker $variant -}}
{{- $image := ternary $ctx.Values.images.workerGpu $ctx.Values.images.worker (eq $variant "gpu") -}}
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "hansard.componentName" (dict "ctx" $ctx "component" $component) }}
  namespace: {{ include "hansard.namespace" $ctx }}
  labels:
    {{- include "hansard.componentLabels" (dict "ctx" $ctx "component" $component) | nindent 4 }}
    hansard.io/role: worker
    hansard.io/compute: {{ $variant }}
  {{- with $ctx.Values.commonAnnotations }}
  annotations:
    {{- toYaml . | nindent 4 }}
  {{- end }}
spec:
  {{- include "hansard.workerReplicas" (dict "ctx" $ctx "component" $component "replicas" $tuning.replicaCount) | nindent 2 }}
  revisionHistoryLimit: {{ $ctx.Values.worker.revisionHistoryLimit }}
  selector:
    matchLabels:
      {{- include "hansard.componentSelectorLabels" (dict "ctx" $ctx "component" $component) | nindent 6 }}
  template:
    metadata:
      labels:
        {{- include "hansard.componentLabels" (dict "ctx" $ctx "component" $component) | nindent 8 }}
        hansard.io/role: worker
        hansard.io/compute: {{ $variant }}
        {{- with $ctx.Values.worker.podLabels }}
        {{- toYaml . | nindent 8 }}
        {{- end }}
      annotations:
        checksum/config: {{ include (print $ctx.Template.BasePath "/configmap.yaml") $ctx | sha256sum }}
        {{- with $ctx.Values.commonAnnotations }}
        {{- toYaml . | nindent 8 }}
        {{- end }}
        {{- with $ctx.Values.worker.podAnnotations }}
        {{- toYaml . | nindent 8 }}
        {{- end }}
    spec:
      {{- include "hansard.imagePullSecrets" $ctx | nindent 6 }}
      serviceAccountName: {{ include "hansard.serviceAccountName.worker" $ctx }}
      automountServiceAccountToken: {{ $ctx.Values.serviceAccounts.worker.automountServiceAccountToken }}
      securityContext:
        {{- include "hansard.podSecurityContext" $ctx | nindent 8 }}
      terminationGracePeriodSeconds: {{ $ctx.Values.worker.terminationGracePeriodSeconds }}
      {{- with $tuning.priorityClassName }}
      priorityClassName: {{ . }}
      {{- end }}
      {{- with $tuning.nodeSelector }}
      nodeSelector:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with $tuning.tolerations }}
      tolerations:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with $tuning.affinity }}
      affinity:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with $tuning.topologySpreadConstraints }}
      topologySpreadConstraints:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with (include "hansard.models.initContainers" $ctx) }}
      initContainers:
        {{- . | trim | nindent 8 }}
      {{- end }}
      containers:
        - name: worker
          image: {{ include "hansard.image" (dict "ctx" $ctx "image" $image) }}
          imagePullPolicy: {{ $image.pullPolicy }}
          args:
            {{- toYaml $ctx.Values.worker.args | nindent 12 }}
          ports:
            - name: metrics
              containerPort: {{ $ctx.Values.worker.metricsPort }}
              protocol: TCP
          envFrom:
            {{- include "hansard.envFrom" $ctx | nindent 12 }}
          env:
            {{- include "hansard.commonEnv" $ctx | nindent 12 }}
            - name: HANSARD_ASR__DEVICE
              value: {{ ternary "cuda" "cpu" (eq $variant "gpu") | quote }}
            - name: HANSARD_DIARIZATION__DEVICE
              value: {{ ternary "cuda" "cpu" (eq $variant "gpu") | quote }}
            - name: WORKER_COMPUTE
              value: {{ $variant | quote }}
            {{- with $ctx.Values.config.extraEnv }}
            {{- toYaml . | nindent 12 }}
            {{- end }}
            {{- with $ctx.Values.worker.extraEnv }}
            {{- toYaml . | nindent 12 }}
            {{- end }}
          resources:
            {{- $resources := deepCopy $tuning.resources }}
            {{- if eq $variant "gpu" }}
            {{- /*
              The schedulable GPU resource name is a value, not a constant:
              with GPU Operator time-slicing and renameByDefault: true the
              device presented to the scheduler is nvidia.com/gpu.shared.
            */}}
            {{- $gpuRequest := dict $ctx.Values.worker.gpu.resourceName $ctx.Values.worker.gpu.count }}
            {{- $_ := set $resources "limits" (merge (default (dict) $resources.limits) $gpuRequest) }}
            {{- $_ := set $resources "requests" (merge (default (dict) $resources.requests) $gpuRequest) }}
            {{- end }}
            {{- toYaml $resources | nindent 12 }}
          securityContext:
            {{- include "hansard.containerSecurityContext" $ctx | nindent 12 }}
          livenessProbe:
            exec:
              command: ["/bin/sh", "-c", "test -f /tmp/hansard-worker.alive"]
            initialDelaySeconds: 60
            periodSeconds: 30
            failureThreshold: 4
          volumeMounts:
            {{- include "hansard.scratchVolumeMounts" $ctx | trim | nindent 12 }}
            {{- include "hansard.models.volumeMounts" $ctx | trim | nindent 12 }}
            {{- include "hansard.ca.volumeMounts" $ctx | trim | nindent 12 }}
            - name: workspace
              mountPath: {{ $ctx.Values.config.workspace }}
      volumes:
        {{- include "hansard.scratchVolumes" $ctx | trim | nindent 8 }}
        {{- include "hansard.models.volumes" $ctx | trim | nindent 8 }}
        {{- include "hansard.ca.volumes" $ctx | trim | nindent 8 }}
        - name: workspace
          emptyDir:
            sizeLimit: 20Gi
{{- end -}}
