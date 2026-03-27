"""S3-compatible object storage for interactive files.

Provides a unified interface for file storage that works with:
- AWS S3
- Scaleway Object Storage
- MinIO
- Local filesystem (fallback when S3 not configured)
"""

import logging
import mimetypes
from pathlib import Path
from typing import BinaryIO, Optional

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from . import config

logger = logging.getLogger(__name__)

# Initialize S3 client if configured
s3_client = None

if config.USE_S3:
    s3_client = boto3.client(
        "s3",
        endpoint_url=config.S3_ENDPOINT,
        aws_access_key_id=config.S3_ACCESS_KEY,
        aws_secret_access_key=config.S3_SECRET_KEY,
        region_name=config.S3_REGION,
        config=BotoConfig(signature_version="s3v4"),
    )
    logger.info(f"S3 storage enabled: bucket={config.S3_BUCKET}, endpoint={config.S3_ENDPOINT}")
else:
    logger.info("S3 storage disabled, using local filesystem")


def get_s3_key(path: str) -> str:
    # Normalize path separators and remove leading slash
    path = path.replace("\\", "/").lstrip("/")
    return f"{config.S3_PREFIX}{path}"


def get_local_path(path: str) -> Path:
    path = path.replace("\\", "/").lstrip("/")
    resolved = (config.INTERACTIVE_DIR / path).resolve()
    if not str(resolved).startswith(str(config.INTERACTIVE_DIR.resolve())):
        raise ValueError("Path traversal detected")
    return resolved


def upload_file(path: str, content: bytes, content_type: Optional[str] = None) -> bool:
    if content_type is None:
        content_type, _ = mimetypes.guess_type(path)
        content_type = content_type or "application/octet-stream"

    if config.USE_S3:
        try:
            key = get_s3_key(path)
            s3_client.put_object(
                Bucket=config.S3_BUCKET,
                Key=key,
                Body=content,
                ContentType=content_type,
            )
            logger.debug(f"Uploaded to S3: {key}")
            return True
        except Exception as e:
            logger.error(f"S3 upload failed for {path}: {e}")
            return False
    else:
        try:
            local_path = get_local_path(path)
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(content)
            logger.debug(f"Saved locally: {local_path}")
            return True
        except Exception as e:
            logger.error(f"Local save failed for {path}: {e}")
            return False


def upload_fileobj(path: str, fileobj: BinaryIO, content_type: Optional[str] = None) -> bool:
    content = fileobj.read()
    return upload_file(path, content, content_type)


def download_file(path: str) -> Optional[bytes]:
    if config.USE_S3:
        try:
            key = get_s3_key(path)
            response = s3_client.get_object(Bucket=config.S3_BUCKET, Key=key)
            return response["Body"].read()
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                logger.debug(f"S3 file not found: {path}")
                return None
            logger.error(f"S3 download failed for {path}: {e}")
            return None
        except Exception as e:
            logger.error(f"S3 download failed for {path}: {e}")
            return None
    else:
        try:
            local_path = get_local_path(path)
            if local_path.exists():
                return local_path.read_bytes()
            return None
        except Exception as e:
            logger.error(f"Local read failed for {path}: {e}")
            return None


def get_file_url(path: str, expires_in: int = 3600) -> Optional[str]:
    if config.USE_S3:
        try:
            key = get_s3_key(path)
            url = s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": config.S3_BUCKET, "Key": key},
                ExpiresIn=expires_in,
            )
            return url
        except Exception as e:
            logger.error(f"Failed to generate presigned URL for {path}: {e}")
            return None
    return None


def file_exists(path: str) -> bool:
    if config.USE_S3:
        try:
            key = get_s3_key(path)
            s3_client.head_object(Bucket=config.S3_BUCKET, Key=key)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return False
            logger.error(f"S3 head_object failed for {path}: {e}")
            return False
    else:
        try:
            return get_local_path(path).exists()
        except ValueError:
            return False


def delete_file(path: str) -> bool:
    if config.USE_S3:
        try:
            key = get_s3_key(path)
            s3_client.delete_object(Bucket=config.S3_BUCKET, Key=key)
            logger.debug(f"Deleted from S3: {key}")
            return True
        except Exception as e:
            logger.error(f"S3 delete failed for {path}: {e}")
            return False
    else:
        try:
            local_path = get_local_path(path)
            if local_path.exists():
                local_path.unlink()
                logger.debug(f"Deleted locally: {local_path}")
            return True
        except Exception as e:
            logger.error(f"Local delete failed for {path}: {e}")
            return False


def list_files(prefix: str = "") -> list[dict]:
    files = []

    if config.USE_S3:
        try:
            s3_prefix = get_s3_key(prefix)
            paginator = s3_client.get_paginator("list_objects_v2")

            for page in paginator.paginate(Bucket=config.S3_BUCKET, Prefix=s3_prefix):
                for obj in page.get("Contents", []):
                    # Remove the S3 prefix to get relative path
                    rel_path = obj["Key"][len(config.S3_PREFIX) :]
                    files.append(
                        {
                            "path": rel_path,
                            "size": obj["Size"],
                            "last_modified": obj["LastModified"],
                        }
                    )
        except Exception as e:
            logger.error(f"S3 list failed for prefix {prefix}: {e}")
    else:
        try:
            base_path = get_local_path(prefix)
            if base_path.exists():
                for file_path in base_path.rglob("*"):
                    if file_path.is_file():
                        rel_path = str(file_path.relative_to(config.INTERACTIVE_DIR))
                        stat = file_path.stat()
                        files.append(
                            {
                                "path": rel_path,
                                "size": stat.st_size,
                                "last_modified": stat.st_mtime,
                            }
                        )
        except Exception as e:
            logger.error(f"Local list failed for prefix {prefix}: {e}")

    return files


def list_directories(prefix: str = "") -> list[str]:
    directories = set()

    if config.USE_S3:
        try:
            s3_prefix = get_s3_key(prefix)
            # Use delimiter to get "directories"
            response = s3_client.list_objects_v2(
                Bucket=config.S3_BUCKET,
                Prefix=s3_prefix,
                Delimiter="/",
            )
            for common_prefix in response.get("CommonPrefixes", []):
                # Extract directory name from prefix
                dir_path = common_prefix["Prefix"][len(config.S3_PREFIX) :].rstrip("/")
                if "/" in dir_path:
                    dir_name = dir_path.split("/")[-1]
                else:
                    dir_name = dir_path
                directories.add(dir_name)
        except Exception as e:
            logger.error(f"S3 list directories failed for prefix {prefix}: {e}")
    else:
        try:
            base_path = get_local_path(prefix) if prefix else config.INTERACTIVE_DIR
            if base_path.exists():
                for item in base_path.iterdir():
                    if item.is_dir():
                        directories.add(item.name)
        except Exception as e:
            logger.error(f"Local list directories failed for prefix {prefix}: {e}")

    return sorted(directories)
