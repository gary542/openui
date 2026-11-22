"""Storage for shared components.

Shares are kept in the database (``Share`` table) unless an S3 compatible bucket
is configured via AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY (and optionally
AWS_ENDPOINT_URL_S3 / BUCKET_NAME), in which case the original S3 behaviour is
used. boto3 is an optional dependency (``pip install openui[s3]``) so that
serverless deployments stay small.
"""
import gzip
import re
from io import BytesIO
from typing import Optional

from .. import config

_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_s3 = None


class ShareNotFound(Exception):
    pass


class InvalidShareId(ValueError):
    pass


def _key_to_id(name: str) -> str:
    # Callers pass "<id>.json"
    share_id = name[: -len(".json")] if name.endswith(".json") else name
    if not _ID_RE.match(share_id):
        raise InvalidShareId("Invalid share id")
    return share_id


def _s3_client():
    global _s3
    if _s3 is None:
        import boto3

        _s3 = boto3.client("s3", endpoint_url=config.AWS_ENDPOINT_URL_S3)
    return _s3


def upload(name: str, data: str):
    share_id = _key_to_id(name)
    if config.USE_S3:
        gzip_buffer = BytesIO()
        with gzip.GzipFile(mode="wb", fileobj=gzip_buffer) as gzip_file:
            gzip_file.write(data.encode("utf-8"))
        return _s3_client().put_object(
            Bucket=config.BUCKET_NAME,
            Key=name,
            Body=gzip_buffer.getvalue(),
            ContentEncoding="gzip",
            ContentType="application/json",
        )
    from ..db.models import Share
    import datetime

    Share.insert(
        id=share_id, data=data, created_at=datetime.datetime.now()
    ).on_conflict(conflict_target=[Share.id], update={Share.data: data}).execute()


def download(name: str) -> bytes:
    share_id = _key_to_id(name)
    if config.USE_S3:
        response = _s3_client().get_object(Bucket=config.BUCKET_NAME, Key=name)
        return gzip.decompress(response["Body"].read())
    from ..db.models import Share

    share: Optional[Share] = Share.get_or_none(Share.id == share_id)
    if share is None:
        raise ShareNotFound(share_id)
    return share.data.encode("utf-8")
