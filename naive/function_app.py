import json
import logging
import os

import azure.functions as func
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)


def read_json(container, blob_name):
    blob = container.get_blob_client(blob_name)
    return json.loads(blob.download_blob().readall())


@app.route(route="enforce-consent", methods=["GET", "POST"])
def enforce_consent(req: func.HttpRequest) -> func.HttpResponse:
    """Intentionally unsafe baseline: checks only whether a consent record exists."""
    try:
        account_url = os.environ["CONSENT_STORAGE_ACCOUNT_URL"]
        service = BlobServiceClient(
            account_url=account_url,
            credential=DefaultAzureCredential()
        )
        input_container = service.get_container_client("input")
        output_container = service.get_container_client("output")

        consents = read_json(input_container, "consents.json")
        observations = read_json(input_container, "observations.json")

        patients_with_a_consent_record = {
            consent.get("subject", {}).get("reference", "")
            for consent in consents
        }

        included = []
        excluded = []
        for observation in observations:
            patient = observation.get("subject", {}).get("reference", "")
            if patient in patients_with_a_consent_record:
                included.append(observation)
            else:
                excluded.append(observation)

        bundle = {
            "resourceType": "Bundle",
            "type": "collection",
            "entry": [{"resource": item} for item in included]
        }
        output_container.upload_blob(
            name="naive_research_extract.json",
            data=json.dumps(bundle, indent=2),
            overwrite=True
        )

        result = {
            "message": "Naive extraction completed. This baseline is intentionally unsafe.",
            "observations_received": len(observations),
            "observations_included": len(included),
            "observations_excluded": len(excluded),
            "extract_blob": "output/naive_research_extract.json",
            "warning": "A consent record exists check does not validate status, purpose, scope, or validity dates."
        }
        logging.warning(
            "NAIVE baseline completed. Received=%d Included=%d Excluded=%d",
            len(observations), len(included), len(excluded)
        )
        return func.HttpResponse(
            json.dumps(result), mimetype="application/json", status_code=200
        )
    except Exception:
        logging.exception("Naive extraction failed")
        return func.HttpResponse(
            "Naive extraction failed. Check Function logs.", status_code=500
        )
