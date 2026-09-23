# Cosign Status — Image Supply Chain Attestation

> **Audit 2026-09-21 P2**: cosign attestation deferred from R3 (supply-chain V4).
> **This document** captures current state (2026-09-21) и recommended next steps.

## Verification (2026-09-21)

### Local image check

```
$ sg docker -c "docker images --digests | grep gd-integration"
gd-integration-tools       light       <none>    92f683065591   4 weeks ago   2.12GB
```

`RepoDigests: []` (пустой) — image **НЕ pushed в registry** и **НЕ signed**.

### Cosign verification attempt

```bash
$ /tmp/cosign verify --insecure-ignore-tlog \
    --certificate-identity-regexp '.*' \
    --certificate-oidc-issuer-regexp '.*' \
    gd-integration-tools:light
```

```
Error: GET https://index.docker.io/v2/library/gd-integration-tools/manifests/light:
       UNAUTHORIZED: authentication required
```

**Root cause**: cosign verify требует доступа к registry. Local-only image
не может быть верифицирован без `--local-image` flag или push в registry.

## State

| Проверка | Status | Notes |
|---|---|---|
| Image built | ✅ | `gd-integration-tools:light` exists |
| Image digest computed | ✅ | `92f683065591` |
| Image pushed to registry | ❌ | `RepoDigests: []` |
| Image signed by cosign | ❌ | no signature attached |
| Cosign verification pipeline | ❌ | no CI job to verify signatures |
| Keyless signing infra | ❌ | no Fulcio/Rekor configured |

## Recommended Next Steps

### Sprint 37 (priority order)

1. **Build local cosign verification helper**:
   ```bash
   cosign verify --local-image --key cosign.pub gd-integration-tools:light
   ```

2. **Generate cosign key pair** (per-environment):
   ```bash
   cosign generate-key-pair
   # Store private key in Vault, public key in repo as cosign.pub
   ```

3. **Add cosign sign step в `image.yml`**:
   ```yaml
   - name: Sign image
     run: |
       cosign sign --key env://COSIGN_KEY gd-integration-tools:${{ github.sha }}
   ```

4. **Add cosign verify step в release-gate**:
   ```yaml
   - name: Verify image signature
     run: cosign verify --key cosign.pub gd-integration-tools:${{ github.sha }}
   ```

5. **Configure transparency log (Rekor)** для non-repudiation.

## Local end-to-end verified (2026-09-21)

```
1. Generated key pair:        cosign.key (private) + cosign.pub (public)
2. Started local registry:    docker run -d -p 5000:5000 registry:2
3. Tagged image:              docker tag gd-integration-tools:light localhost:5000/gd-integration-tools:light
4. Pushed image:              docker push localhost:5000/gd-integration-tools:light → sha256:fe791e01643...
5. Signed image:              cosign sign --key cosign.key --tlog-upload=false → "Pushing signature to: localhost:5000/gd-integration-tools"
6. Verified signature:        cosign verify --key cosign.pub → ✅ "The cosign claims were validated, signatures verified"

Test keys saved to: .cosign-test/ (NOT for production)
- cosign.pub — public key (can commit)
- cosign.key — private key (DO NOT commit, .gitignore recommended)
```

## Honest Assessment

**P0 release-gate невозможен без cosign signing** — но это **deferred** в R3
(см. `docs/audit/principal-audit-2026-07-27/`). Audit recommendation
"supply-chain V4" — это **multi-sprint work**, не single-task fix.

**Для pre-production**:
- Local image работает и live-tested (см. CURRENT_STATUS.md)
- Supply chain attestation — **NOT required для dev/staging**
- Supply chain attestation — **REQUIRED для production release**

Out of scope локальной сессии. Зафиксировано для следующего sprint.
