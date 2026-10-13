BOT_NAME = "rover"

SPIDER_MODULES = ["rover.spiders"]
NEWSPIDER_MODULE = "rover.spiders"

ROBOTSTXT_OBEY = True          # the site serves no robots.txt, so nothing is blocked

# Be a polite guest on a government service.
CONCURRENT_REQUESTS = 2
CONCURRENT_REQUESTS_PER_DOMAIN = 2
DOWNLOAD_DELAY = 1.0
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 1.0
AUTOTHROTTLE_MAX_DELAY = 20.0
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.5

# Dataverse ships ~250 KB of attribute metadata per record, so a 50-record
# page is 10-15 MB. Raise the ceilings or Scrapy will drop the responses.
DOWNLOAD_MAXSIZE = 0
DOWNLOAD_WARNSIZE = 0
DOWNLOAD_TIMEOUT = 300

RETRY_ENABLED = True
RETRY_TIMES = 3

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/139.0 Safari/537.36"
)
DEFAULT_REQUEST_HEADERS = {"Accept-Language": "en-AU,en;q=0.9"}

COOKIES_ENABLED = True         # the antiforgery token is bound to a session cookie

FEED_EXPORT_ENCODING = "utf-8"
FEED_EXPORT_INDENT = 2

REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
ADDONS = {}
