# cosign signing policy

К5 (Wave K5/supply-chain). Все Docker images подписываются keyless
через GitHub OIDC + Sigstore (cosign).

## Что подписывается

* GHCR images, собранные на `tag push v*.*.*`;
* SBOM artifacts (через `cosign attest`).

## Как проверить подпись

```bash
cosign verify \
  --certificate-identity "https://github.com/<owner>/<repo>/.github/workflows/security.yml@refs/tags/<tag>" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  ghcr.io/<owner>/<repo>:<tag>
```

## Workflow

`.github/workflows/security.yml::cosign-sign`:
* Запускается **только** на `tag push v*.*.*`.
* Использует `sigstore/cosign-installer@v3` + `permissions: id-token: write`.
* Без приватного ключа (keyless через OIDC).

## Что НЕ подписывается keyless

* Локальные сборки разработчиков (`make docker-build`) — keyless требует CI OIDC.
* Тестовые images — фильтр `if: startsWith(github.ref, 'refs/tags/')`.
