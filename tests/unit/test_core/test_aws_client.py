"""Smoke tests for the AwsClient wrapper."""

from __future__ import annotations

from cost_optimizer.aws.client import AwsClient


def test_get_account_id_returns_12_digit_string(aws_client: AwsClient) -> None:
    account_id = aws_client.get_account_id()
    assert isinstance(account_id, str)
    assert len(account_id) == 12
    assert account_id.isdigit()


def test_client_is_cached(aws_client: AwsClient) -> None:
    """Repeated calls for the same service should return the same client object."""
    ec2_first = aws_client.client("ec2")
    ec2_second = aws_client.client("ec2")
    assert ec2_first is ec2_second


def test_typed_accessors_work(aws_client: AwsClient) -> None:
    """The .ec2 and .cloudwatch properties should yield working clients."""
    assert aws_client.ec2 is not None
    assert aws_client.cloudwatch is not None
