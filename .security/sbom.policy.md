# SBOM policy

К5 (Wave K5/supply-chain). SBOM — обязательный артефакт каждого релиза.

## Что входит в SBOM

* **CycloneDX 1.4+ JSON** (`dist/sbom.cdx.json`) — full Python deps tree.
* Генератор — `cyclonedx-py environment` (анализирует активный venv).
* Артефакт прикрепляется к GitHub Release через `softprops/action-gh-release@v2`.

## Когда обновляется

* На **каждом** push в `main` (job `sbom` в `.github/workflows/security.yml`);
* На **каждом** tag push (release-attach).

## Как читать SBOM

```bash
make sbom
jq '.components[] | {name, version, type}' dist/sbom.cdx.json | head -20
```

## Связанные политики

* `pip-audit-allowlist.txt` — известные CVE, временно проигнорированные;
* `cosign.policy.md` — keyless подпись Docker images;
* `zap-rules.tsv` — OWASP ZAP baseline тонкая настройка.
