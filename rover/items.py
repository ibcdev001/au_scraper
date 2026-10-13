"""Two plain-dict item types so the feed exporter can split them into
separate JSON files. Fields are dynamic (they come straight from Dataverse),
so a dict subclass beats a fixed-field scrapy.Item here."""


class ApprovalItem(dict):
    """One row of a published-approvals list grid."""


class DetailItem(dict):
    """One parsed detail page."""
