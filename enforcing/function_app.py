
import csv
import io
import json
import logging
import os
from datetime import date, datetime

import azure.functions as func
from azure.storage.blob import BlobServiceClient

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)


def read_json(container, blob_name):
    blob = container.get_blob_client(blob_name)
    return json.loads(blob.download_blob().readall())


def has_code(concept, code):
    return any(
        item.get("code") == code
        for item in concept.get("coding", [])
    )


def consent_datetime(consent):
    """Return the consent's recorded date/time for ordering."""
    value = consent.get("dateTime") or consent.get("date")
    if not value:
        return datetime.min

    try:
        # Handles ISO dates and timestamps, including timezone offsets.
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        # Normalize timezone-aware timestamps to naive UTC for comparison.
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(
                __import__("datetime").timezone.utc
            ).replace(tzinfo=None)
        return parsed
    except (ValueError, TypeError):
        return datetime.min


def check_consent(consent, today):
    if consent.get("status") != "active":
        return False, "Consent is inactive or withdrawn"

    if not has_code(consent.get("scope", {}), "research"):
        return False, "Consent scope is not research"

    provision = consent.get("provision", {})
    if provision.get("type") != "permit":
        return False, "Consent provision does not permit use"

    if not any(
        item.get("code") == "HRESCH"
        for item in provision.get("purpose", [])
    ):
        return False, "Research purpose is not permitted"

    period = provision.get("period", {})
    start = period.get("start")
    end = period.get("end")

    if not start or not end:
        return False, "Consent validity period is missing"

    try:
        if not (
            date.fromisoformat(start[:10])
            <= today
            <= date.fromisoformat(end[:10])
        ):
            return False, "Consent is outside its validity period"
    except (ValueError, TypeError):
        return False, "Consent validity period is invalid"

    return True, "Valid research consent"


@app.route(route="enforce-consent", methods=["GET", "POST"])
def enforce_consent(req: func.HttpRequest) -> func.HttpResponse:
    try:
        connection_string = os.environ[
            "CONSENT_STORAGE_CONNECTION_STRING"
        ]

        service = BlobServiceClient.from_connection_string(
            connection_string
        )

        input_container = service.get_container_client("input")
        output_container = service.get_container_client("output")

        consents = read_json(input_container, "consents.json")
        observations = read_json(input_container, "observations.json")

        today = date.today()

        # Group consents by patient, preserving the full consent history.
        consent_by_patient = {}
        for consent in consents:
            patient = consent.get("subject", {}).get("reference", "")
            if patient:
                consent_by_patient.setdefault(patient, []).append(consent)

        approved = []
        audit_rows = []

        for observation in observations:
            patient = observation.get("subject", {}).get("reference", "")
            candidates = consent_by_patient.get(patient, [])

            if not candidates:
                permitted = False
                reason = "No consent record found"
            else:
                # Only the most recently recorded consent governs the decision.
                latest_consent = max(
                    candidates,
                    key=consent_datetime
                )
                permitted, reason = check_consent(latest_consent, today)

            if permitted:
                approved.append(observation)

            audit_rows.append({
                "observation_id": observation.get("id", ""),
                "patient_reference": patient,
                "decision": "INCLUDED" if permitted else "EXCLUDED",
                "reason": reason
            })

        bundle = {
            "resourceType": "Bundle",
            "type": "collection",
            "entry": [
                {"resource": item}
                for item in approved
            ]
        }

        output_container.upload_blob(
            name="research_extract.json",
            data=json.dumps(bundle, indent=2),
            overwrite=True
        )

        csv_buffer = io.StringIO()
        fields = [
            "observation_id",
            "patient_reference",
            "decision",
            "reason"
        ]
        writer = csv.DictWriter(
            csv_buffer,
            fieldnames=fields
        )
        writer.writeheader()
        writer.writerows(audit_rows)

        output_container.upload_blob(
            name="consent_audit.csv",
            data=csv_buffer.getvalue(),
            overwrite=True
        )

        excluded_count = len(observations) - len(approved)

        logging.info(
            "Consent processing completed. Received=%d Included=%d Excluded=%d",
            len(observations),
            len(approved),
            excluded_count
        )

        return func.HttpResponse(
            json.dumps({
                "message": "Consent validation completed",
                "observations_received": len(observations),
                "observations_included": len(approved),
                "observations_excluded": excluded_count,
                "extract_blob": "output/research_extract.json",
                "audit_blob": "output/consent_audit.csv"
            }),
            mimetype="application/json",
            status_code=200
        )

    except Exception:
        logging.exception("Consent processing failed")
        return func.HttpResponse(
            "Consent processing failed. Check Function logs.",
            status_code=500
        )
