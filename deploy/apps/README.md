# deploy/apps

One Argo CD `Application` per file. The root app (`deploy/root-app.yaml`)
installs everything here that's on `main`, ordered by each file's
`argocd.argoproj.io/sync-wave` annotation (Task 5.3).
