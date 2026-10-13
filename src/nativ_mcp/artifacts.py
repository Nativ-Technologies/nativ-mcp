"""Durable hosted outputs with short-lived download URLs."""

import asyncio
from datetime import timedelta
from uuid import uuid4


class GCSArtifactStore:
    def __init__(self, bucket: str, signing_account: str):
        import google.auth
        from google.cloud import storage

        # Storage-only ADC scopes allow uploads but cannot call IAM SignBlob.
        # IAM permissions still restrict this account to its output bucket and
        # signing as itself; the token also needs the cloud-platform scope.
        credentials, project = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        self.client = storage.Client(project=project, credentials=credentials)
        self.bucket = self.client.bucket(bucket)
        self.signing_account = signing_account

    async def save(self, data: bytes, filename: str, content_type: str) -> str:
        return await asyncio.to_thread(self._save, data, filename, content_type)

    def _save(self, data: bytes, filename: str, content_type: str) -> str:
        from google.auth.transport.requests import Request

        # Never use caller-controlled directory names or overwrite another call.
        blob = self.bucket.blob(f"outputs/{uuid4().hex}/{filename}")
        blob.upload_from_string(data, content_type=content_type, if_generation_match=0)
        credentials = self.client._credentials
        if not credentials.valid:
            credentials.refresh(Request())
        return blob.generate_signed_url(
            version="v4", expiration=timedelta(hours=1), method="GET",
            service_account_email=self.signing_account, access_token=credentials.token,
        )
