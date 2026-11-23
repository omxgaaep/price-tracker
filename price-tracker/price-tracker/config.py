# ---------------------------------------------------------------
#  Price tracker settings — edit this file to change what's tracked
# ---------------------------------------------------------------

# Which product families count. Anything else (iPhone Air, iPhone 15,
# iPads, accessories...) is ignored.
IPHONE_MODELS = ["16", "17", "17e"]
MACBOOK_LINES = ["Air"]                 # MacBook Air only (13" and 15")
MACBOOK_CHIPS = ["M5"]                  # latest chip only; add "M6" etc. when it comes out

# Only track the base (cheapest) configuration of each model:
# smallest storage for iPhones, smallest storage + RAM for each MacBook
# size/chip (e.g. MacBook Air 13" M5 16GB/512GB, not the 1TB/24GB one).
# Set to False to track every storage/RAM option.
LOWEST_SPEC_ONLY = True

# Searches typed into each store's search box
SEARCHES = ["iphone 16", "iphone 17", "iphone 17e", "macbook air"]

# Stores. "search" uses a real (headless) browser to read the store's
# search results page; {q} is replaced with each search above.
# "shopify_collection" reads JB Hi-Fi's product feed directly (fast + reliable).
RETAILERS = [
    {"name": "JB Hi-Fi", "type": "shopify_collection",
     "url": "https://www.jbhifi.com.au/collections/mobile-phones/products.json",
     "base": "https://www.jbhifi.com.au/products/"},
    {"name": "JB Hi-Fi", "type": "search",
     "url": "https://www.jbhifi.com.au/search?query={q}", "only": ["macbook air"]},
    {"name": "The Good Guys", "type": "search",
     "url": "https://www.thegoodguys.com.au/search?q={q}"},
    {"name": "Officeworks", "type": "search",
     "url": "https://www.officeworks.com.au/shop/officeworks/search?q={q}"},
    {"name": "Costco", "type": "search",
     "url": "https://www.costco.com.au/search?text={q}"},
    # Harvey Norman and Amazon AU were removed: they block automated checks.
    # Apple isn't scraped: its own prices are fixed RRP and only show as
    # "From $X" per model, so it would never be the cheapest anyway.
]

# Ignore anything cheaper than this (stops phone cases, "$59/month" plans etc.
# being mistaken for a phone price)
MIN_PRICE = 450

# Only alert if the new low beats the old low by at least this many dollars
MIN_DROP = 5

# If a new price is more than this fraction below the previous low, the email
# flags it as "double-check" (could be a misread, a marketplace seller, etc.)
SUSPICIOUS_DROP = 0.35

# Warn by email if a store returns nothing this many runs in a row
# (usually means the site changed or started blocking the tracker)
FAIL_WARN_AFTER = 6

# Daily summary email of the current cheapest price for every model
# (new-low alerts still go out straight away, every check)
DAILY_SUMMARY = True
SUMMARY_HOUR = 8           # sent with the first check after this hour, Perth time
TIMEZONE = "Australia/Perth"
