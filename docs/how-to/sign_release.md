# Sign release

Keyless cosign подпись Docker images через GitHub OIDC + Sigstore.

## Когда

* На каждом `tag push v*.*.*` (workflow `.github/workflows/security.yml::cosign-sign`);
* Локально — **запрещено** (требует CI OIDC).

## Что подписывается

* GHCR images;
* SBOM (`dist/sbom.cdx.json`) через `cosign attest`.

## Как проверить

```bash
cosign verify \
  --certificate-identity "https://github.com/<owner>/<repo>/.github/workflows/security.yml@refs/tags/<tag>" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  ghcr.io/<owner>/<repo>:<tag>
```

## Связанные политики

* [SBOM policy](../../.security/sbom.policy.md)
* [Cosign policy](../../.security/cosign.policy.md)
