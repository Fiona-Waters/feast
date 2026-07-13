import json
import logging
import os
from typing import Dict, Optional
from urllib.parse import urlparse

import boto3

logger = logging.getLogger(__name__)


class STSCredentialVender:
    """Vends scoped, temporary S3 credentials via STS AssumeRole.

    Uses an inline session policy to restrict each vended credential set
    to a specific S3 prefix (the table/volume location). The resulting
    permissions are the intersection of the master user's policies and
    the inline policy — so credentials can never exceed the master user's
    access.

    MinIO ignores role_arn but requires it for API compatibility.
    """

    def __init__(
        self,
        sts_endpoint: str,
        access_key: str,
        secret_key: str,
        role_arn: str = "arn:aws:iam:::role/feast-vending",
        session_duration: int = 900,
    ):
        self.sts = boto3.client(
            "sts",
            endpoint_url=sts_endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="us-east-1",
        )
        self.role_arn = role_arn
        self.session_duration = session_duration
        self.endpoint = sts_endpoint

    def vend(
        self, table_location: str, principal: str = "anonymous"
    ) -> Dict[str, str]:
        """Mint scoped temporary credentials for a specific S3 location."""
        parsed = urlparse(table_location)
        bucket = parsed.netloc
        prefix = parsed.path.lstrip("/")

        policy = json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["s3:GetObject", "s3:ListBucket"],
                        "Resource": [
                            f"arn:aws:s3:::{bucket}/{prefix}*",
                            f"arn:aws:s3:::{bucket}",
                        ],
                        "Condition": {
                            "StringLike": {"s3:prefix": [f"{prefix}*"]}
                        },
                    }
                ],
            }
        )

        resp = self.sts.assume_role(
            RoleArn=self.role_arn,
            RoleSessionName=f"feast-{principal}",
            Policy=policy,
            DurationSeconds=self.session_duration,
        )
        creds = resp["Credentials"]
        return {
            "s3.access-key-id": creds["AccessKeyId"],
            "s3.secret-access-key": creds["SecretAccessKey"],
            "s3.session-token": creds["SessionToken"],
        }


def create_vender_from_env() -> Optional[STSCredentialVender]:
    """Create a credential vender from environment variables.

    Required env vars:
      STS_ENDPOINT   — S3/STS endpoint (e.g. http://minio:9000)
      STS_ACCESS_KEY — master access key
      STS_SECRET_KEY — master secret key

    Optional env vars:
      STS_ROLE_ARN          — ARN for AssumeRole (dummy value for MinIO)
      STS_SESSION_DURATION  — TTL in seconds (default 900 = 15 min)

    Returns None if the required env vars are not set.
    """
    endpoint = os.environ.get("STS_ENDPOINT")
    access_key = os.environ.get("STS_ACCESS_KEY")
    secret_key = os.environ.get("STS_SECRET_KEY")

    if not all([endpoint, access_key, secret_key]):
        logger.info(
            "STS vending not configured "
            "(missing STS_ENDPOINT / STS_ACCESS_KEY / STS_SECRET_KEY)"
        )
        return None

    logger.info("STS credential vending enabled (endpoint: %s)", endpoint)
    return STSCredentialVender(
        sts_endpoint=endpoint,
        access_key=access_key,
        secret_key=secret_key,
        role_arn=os.environ.get(
            "STS_ROLE_ARN", "arn:aws:iam:::role/feast-vending"
        ),
        session_duration=int(os.environ.get("STS_SESSION_DURATION", "900")),
    )
