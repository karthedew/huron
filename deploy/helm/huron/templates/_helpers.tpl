{{/* The release's resource name, at most 63 characters. */}}
{{- define "huron.fullname" -}}
{{- if contains .Chart.Name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "huron.webName" -}}
{{- printf "%s-web" (include "huron.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "huron.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/* Selector labels; pass a dict with "root" (the top context) and "component". */}}
{{- define "huron.selectorLabels" -}}
app.kubernetes.io/name: {{ .root.Chart.Name }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{- define "huron.image" -}}
{{- printf "%s:%s" .Values.image.repository (default .Chart.AppVersion .Values.image.tag) -}}
{{- end -}}

{{- define "huron.webImage" -}}
{{- printf "%s:%s" .Values.web.image.repository (default .Chart.AppVersion .Values.web.image.tag) -}}
{{- end -}}

{{/* huron.yaml: the config value, verbatim. */}}
{{- define "huron.configFile" -}}
{{- if hasKey .Values.config "database_url" -}}
{{- fail "config.database_url: keep the database URL in database.existingSecret, never in the ConfigMap" -}}
{{- end -}}
{{- toYaml .Values.config -}}
{{- end -}}

{{- define "huron.databaseEnv" -}}
- name: HURON_DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: {{ required "database.existingSecret is required" .Values.database.existingSecret }}
      key: {{ .Values.database.key }}
{{- end -}}

{{- define "huron.containerSecurityContext" -}}
allowPrivilegeEscalation: false
runAsNonRoot: true
capabilities: {drop: ["ALL"]}
seccompProfile: {type: RuntimeDefault}
{{- end -}}
