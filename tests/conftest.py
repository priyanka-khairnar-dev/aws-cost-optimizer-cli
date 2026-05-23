"""Shared pytest fixtures.

Notable patterns:
- ``aws_credentials`` sets fake env vars so boto3 doesn't try to reach IMDS
  or your real credentials in CI.
- ``mocked_aws`` is the entry point for moto — wrap a test body with it
  to get isolated, in-memory AWS.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from moto import mock_aws

from cost_optimizer.aws.client import AwsClient


@pytest.fixture
def aws_credentials() -> None:
    """Stub AWS credentials so boto3 won't try to read real ones."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"


@pytest.fixture
def mocked_aws(aws_credentials: None) -> Iterator[None]:
    """Wrap a test in moto's AWS mock context."""
    with mock_aws():
        yield


@pytest.fixture
def aws_client(mocked_aws: None) -> AwsClient:
    """A real ``AwsClient`` pointed at moto's in-memory AWS."""
    return AwsClient(region="us-east-1")
