"""EC2 on-demand pricing lookups.

The AWS Pricing API is the canonical source for instance prices. It has a
few quirks worth hiding behind a small helper:

- It only lives in two regions (us-east-1 and ap-south-1). You query the
  Pricing API in those regions even when asking about prices in eu-west-3.
- It uses ``location`` strings like "US East (N. Virginia)" rather than
  region codes — we have to translate.
- Responses are deeply nested JSON-as-strings. Awkward.
- It's slow (~1s per call) but results are stable, so caching is essential.

This helper handles all of that for the ``instance_type x region``
on-demand Linux case, which is what idle EC2 detection needs. Other
analyzers can extend it as they need more pricing dimensions.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cost_optimizer.aws.client import AwsClient

logger = logging.getLogger(__name__)

# AWS Pricing API uses location names, not region codes. These are the
# common ones — the full list is at https://docs.aws.amazon.com/.
_REGION_TO_LOCATION: dict[str, str] = {
    "us-east-1": "US East (N. Virginia)",
    "us-east-2": "US East (Ohio)",
    "us-west-1": "US West (N. California)",
    "us-west-2": "US West (Oregon)",
    "eu-west-1": "Europe (Ireland)",
    "eu-west-2": "Europe (London)",
    "eu-west-3": "Europe (Paris)",
    "eu-central-1": "Europe (Frankfurt)",
    "eu-north-1": "Europe (Stockholm)",
    "ap-south-1": "Asia Pacific (Mumbai)",
    "ap-southeast-1": "Asia Pacific (Singapore)",
    "ap-southeast-2": "Asia Pacific (Sydney)",
    "ap-northeast-1": "Asia Pacific (Tokyo)",
    "ap-northeast-2": "Asia Pacific (Seoul)",
    "ca-central-1": "Canada (Central)",
    "sa-east-1": "South America (Sao Paulo)",
}

# Approximate hours in a month for monthly cost estimates. Using 730
# (= 24 * 365.25 / 12) matches AWS's own billing convention.
HOURS_PER_MONTH = 730.0


class PricingLookupError(Exception):
    """Raised when a price can't be determined for an instance type/region."""


class EC2Pricing:
    """On-demand EC2 instance pricing for Linux, shared tenancy.

    Construct once per scan and pass to analyzers — the LRU cache means
    a second lookup of the same (instance_type, region) pair is free.
    """

    def __init__(self, aws_client: AwsClient) -> None:
        # Pricing API only exists in us-east-1 and ap-south-1. We use
        # us-east-1 unconditionally for simplicity.
        self._aws = aws_client
        # Bound the cache so a misbehaving caller can't blow up memory.
        self.hourly_usd = lru_cache(maxsize=512)(self._fetch_hourly_usd)

    def monthly_usd(self, instance_type: str, region: str) -> float:
        """Estimated monthly on-demand cost (Linux, shared tenancy)."""
        return self.hourly_usd(instance_type, region) * HOURS_PER_MONTH

    def _fetch_hourly_usd(self, instance_type: str, region: str) -> float:
        """Look up on-demand hourly price via the AWS Pricing API."""
        location = _REGION_TO_LOCATION.get(region)
        if location is None:
            raise PricingLookupError(
                f"Region {region!r} not mapped to a Pricing API location name. "
                f"Add it to _REGION_TO_LOCATION in core/pricing.py."
            )

        # Pricing API client must be created in us-east-1 regardless of
        # what region we're pricing.
        pricing = self._aws.client("pricing")
        filters = [
            {"Type": "TERM_MATCH", "Field": "ServiceCode", "Value": "AmazonEC2"},
            {"Type": "TERM_MATCH", "Field": "instanceType", "Value": instance_type},
            {"Type": "TERM_MATCH", "Field": "location", "Value": location},
            {"Type": "TERM_MATCH", "Field": "operatingSystem", "Value": "Linux"},
            {"Type": "TERM_MATCH", "Field": "tenancy", "Value": "Shared"},
            {"Type": "TERM_MATCH", "Field": "preInstalledSw", "Value": "NA"},
            {"Type": "TERM_MATCH", "Field": "capacitystatus", "Value": "Used"},
        ]
        logger.debug("Pricing lookup: %s in %s", instance_type, region)

        response = pricing.get_products(ServiceCode="AmazonEC2", Filters=filters, MaxResults=1)
        price_list = response.get("PriceList", [])
        if not price_list:
            raise PricingLookupError(
                f"No price found for {instance_type} in {region}. "
                f"The instance type may be deprecated or unavailable in the region."
            )

        # Each item is a JSON string. The shape is documented at
        # https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/billing-getting-started.html
        product = json.loads(price_list[0])
        on_demand = product["terms"]["OnDemand"]
        # OnDemand is keyed by an opaque offer code; there's exactly one
        # for the filter set above.
        offer = next(iter(on_demand.values()))
        price_dimensions = offer["priceDimensions"]
        dimension = next(iter(price_dimensions.values()))
        usd_per_hour = float(dimension["pricePerUnit"]["USD"])
        return usd_per_hour
