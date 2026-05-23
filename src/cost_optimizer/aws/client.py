"""Thin wrapper around boto3 for testability and ergonomics.

We don't want boto3 calls scattered through analyzer code — it makes mocking
painful and couples business logic to AWS SDK details. The ``AwsClient``
wraps boto3 session/client creation, pagination, and a few common patterns.

Real-world projects often go further (caching, rate limiting, structured
error handling). This is the smallest version that's still useful.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

import boto3
from botocore.config import Config

if TYPE_CHECKING:
    from collections.abc import Iterator

    from mypy_boto3_cloudwatch.client import CloudWatchClient
    from mypy_boto3_ec2.client import EC2Client

logger = logging.getLogger(__name__)


class AwsClient:
    """Lazy, per-region boto3 client factory.

    Usage::

        aws = AwsClient(profile="prod", region="us-east-1")
        for page in aws.paginate("ec2", "describe_instances"):
            for reservation in page["Reservations"]:
                ...
    """

    def __init__(
        self,
        *,
        profile: str | None = None,
        region: str = "us-east-1",
        max_retries: int = 5,
    ) -> None:
        self.profile = profile
        self.region = region
        self._session = boto3.Session(profile_name=profile, region_name=region)
        self._config = Config(
            retries={"max_attempts": max_retries, "mode": "adaptive"},
            user_agent_extra="aws-cost-optimizer/0.1.0",
        )
        self._client_cache: dict[str, Any] = {}

    def client(self, service: str) -> Any:
        """Get (or create) a boto3 client for a service.

        Clients are cached per-instance so analyzers don't repeatedly
        instantiate the same client.
        """
        if service not in self._client_cache:
            logger.debug("Creating boto3 client for %s in %s", service, self.region)
            # boto3's Session.client() has hundreds of typed overloads but no
            # dynamic-string fallback. Cast through Any.
            create = cast(Any, self._session.client)
            self._client_cache[service] = create(service, config=self._config)
        return self._client_cache[service]

    # Convenience accessors with proper types — keeps analyzer code clean.
    @property
    def ec2(self) -> EC2Client:
        return cast("EC2Client", self.client("ec2"))

    @property
    def cloudwatch(self) -> CloudWatchClient:
        return cast("CloudWatchClient", self.client("cloudwatch"))

    def paginate(
        self,
        service: str,
        operation: str,
        **kwargs: Any,
    ) -> Iterator[dict[str, Any]]:
        """Iterate over paginated AWS API responses.

        Boto3 pagination is verbose; this hides the boilerplate. Most
        ``describe_*`` and ``list_*`` operations are paginated even when
        accounts are small, so analyzer code should always use this.
        """
        client = self.client(service)
        paginator = client.get_paginator(operation)
        yield from paginator.paginate(**kwargs)

    def get_account_id(self) -> str:
        """Return the 12-digit AWS account ID of the active credentials."""
        sts = self.client("sts")
        identity: dict[str, str] = sts.get_caller_identity()
        return identity["Account"]
