from functools import lru_cache

import boto3

from backend.settings import settings


@lru_cache
def s3():
    config = settings()
    return boto3.client("s3", endpoint_url=config.s3_endpoint, region_name=config.s3_region)


def put(key: str, content: bytes):
    config = settings()
    if config.storage_backend == "s3":
        s3().put_object(Bucket=config.s3_bucket, Key=key, Body=content, ContentType="application/pdf")
    else:
        target = config.storage_root / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def get(key: str) -> bytes:
    config = settings()
    if config.storage_backend == "s3":
        response = s3().get_object(Bucket=config.s3_bucket, Key=key)
        with response["Body"] as body:
            return body.read()
    return (config.storage_root / key).read_bytes()


def remove(key: str):
    config = settings()
    if config.storage_backend == "s3":
        s3().delete_object(Bucket=config.s3_bucket, Key=key)
    else:
        (config.storage_root / key).unlink(missing_ok=True)
