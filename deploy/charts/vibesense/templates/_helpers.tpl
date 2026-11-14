{{/* Labels on every object. */}}
{{- define "vibesense.labels" -}}
app.kubernetes.io/name: vibesense
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end }}

{{/* Pod selector for one workload. Args: dict "component" <name>. */}}
{{- define "vibesense.selectorLabels" -}}
app.kubernetes.io/name: vibesense
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{/* Full image reference. Args: dict "root" $ "image" "app"|"ai". */}}
{{- define "vibesense.image" -}}
{{- $img := index .root.Values.images .image | required (printf "images.%s is not defined" .image) -}}
{{- $registry := required "registry is required (Argo CD sets it, Task 6.3)" .root.Values.registry -}}
{{- $tag := required (printf "images.%s.tag is required" .image) $img.tag -}}
{{- printf "%s/%s:%s" $registry $img.repository $tag -}}
{{- end }}

{{/*
Container env: shared values.env, then the workload's own env (wins on a
clash), then each listed secret var as a secretKeyRef.
Args: dict "root" $ "env" <map> "secretEnv" <list>.
*/}}
{{- define "vibesense.env" -}}
{{- $root := .root -}}
{{- $plain := merge (dict) (.env | default dict) $root.Values.env -}}
{{- range $name := keys $plain | sortAlpha }}
- name: {{ $name }}
  value: {{ get $plain $name | quote }}
{{- end }}
{{- range $name := .secretEnv | default list }}
{{- $src := index $root.Values.secretEnv $name | required (printf "secretEnv has no source for %s" $name) }}
- name: {{ $name }}
  valueFrom:
    secretKeyRef:
      name: {{ $src.secret }}
      key: {{ $src.key }}
{{- end }}
{{- end }}

{{/* Pod-level security: the image's non-root user (Dockerfile, UID 10001). */}}
{{- define "vibesense.podSecurityContext" -}}
runAsNonRoot: true
runAsUser: 10001
runAsGroup: 10001
fsGroup: 10001
seccompProfile:
  type: RuntimeDefault
{{- end }}

{{/* Container-level security. /tmp is the only writable path (an emptyDir). */}}
{{- define "vibesense.containerSecurityContext" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: ["ALL"]
{{- end }}
