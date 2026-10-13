# Consent lab function package

This package contains two Azure Functions Python v2 projects:

- `naive/`: intentionally unsafe baseline. It includes observations whenever a consent record exists for the patient, without checking status, scope, purpose, or validity dates.
- `enforcing/`: validates consent status, research scope, permitted research purpose, and validity dates, and writes a CSV audit file.

## Required Function App setting

Set `CONSENT_STORAGE_ACCOUNT_URL` to the URL of the storage account containing the private `input` and `output` containers, for example:
`https://<storage-account-name>.blob.core.windows.net`

Enable the Function App's system-assigned managed identity and grant it **Storage Blob Data Contributor** at the scope of that same storage account.

## Deployment

From the selected project directory, publish that project's contents to the target Function App using Azure Functions Core Tools. Publish `naive` first, test it, then publish `enforcing` to replace the baseline implementation. Both use the same HTTP route: `enforce-consent`.

The package does not contain patient data. Upload `consents.json` and `observations.json` to the `input` container separately.

## Important

This is a synthetic educational demonstration using a subset of FHIR-like Consent fields. It is not a complete FHIR R4 implementation and should not be used for real patient data or clinical decisions. Test the expected counts against the exact input JSON supplied with the lab.
