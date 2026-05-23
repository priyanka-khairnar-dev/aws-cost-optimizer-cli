"""Tests for the EC2Pricing helper."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from cost_optimizer.aws.client import AwsClient
from cost_optimizer.core.pricing import HOURS_PER_MONTH, EC2Pricing, PricingLookupError


def _build_pricing_response(usd_per_hour: float) -> dict[str, Any]:
    """Mock the AWS Pricing API response shape."""
    product = {
        "terms": {
            "OnDemand": {
                "OFFER_CODE.JRTCKXETXF": {
                    "priceDimensions": {
                        "OFFER_CODE.JRTCKXETXF.6YS6EN2CT7": {
                            "pricePerUnit": {"USD": str(usd_per_hour)},
                            "unit": "Hrs",
                        }
                    }
                }
            }
        }
    }
    return {"PriceList": [json.dumps(product)]}


class TestPricing:
    def test_monthly_usd_uses_730_hours(self, aws_client: AwsClient) -> None:
        # Patch the pricing client on the wrapper.
        pricing = EC2Pricing(aws_client)
        fake_client = MagicMock()
        fake_client.get_products.return_value = _build_pricing_response(0.1)
        aws_client._client_cache["pricing"] = fake_client

        monthly = pricing.monthly_usd("m5.large", "us-east-1")
        assert monthly == pytest.approx(0.1 * HOURS_PER_MONTH)

    def test_unknown_region_raises(self, aws_client: AwsClient) -> None:
        pricing = EC2Pricing(aws_client)
        with pytest.raises(PricingLookupError, match="not mapped"):
            pricing.hourly_usd("m5.large", "antarctica-1")

    def test_empty_price_list_raises(self, aws_client: AwsClient) -> None:
        pricing = EC2Pricing(aws_client)
        fake_client = MagicMock()
        fake_client.get_products.return_value = {"PriceList": []}
        aws_client._client_cache["pricing"] = fake_client

        with pytest.raises(PricingLookupError, match="No price found"):
            pricing.hourly_usd("xyz.huge", "us-east-1")

    def test_results_are_cached(self, aws_client: AwsClient) -> None:
        """Second lookup of same (instance_type, region) shouldn't re-call AWS."""
        pricing = EC2Pricing(aws_client)
        fake_client = MagicMock()
        fake_client.get_products.return_value = _build_pricing_response(0.5)
        aws_client._client_cache["pricing"] = fake_client

        pricing.hourly_usd("m5.large", "us-east-1")
        pricing.hourly_usd("m5.large", "us-east-1")
        pricing.hourly_usd("m5.large", "us-east-1")

        assert fake_client.get_products.call_count == 1

    def test_cache_distinguishes_region(self, aws_client: AwsClient) -> None:
        pricing = EC2Pricing(aws_client)
        fake_client = MagicMock()
        fake_client.get_products.return_value = _build_pricing_response(0.5)
        aws_client._client_cache["pricing"] = fake_client

        pricing.hourly_usd("m5.large", "us-east-1")
        pricing.hourly_usd("m5.large", "eu-west-1")

        assert fake_client.get_products.call_count == 2
