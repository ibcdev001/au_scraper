# Local equivalents of what .github/workflows/refresh.yml runs in CI.
PY := ./.venv/bin/python

.PHONY: install test crawl pair page refresh check serve clean

install:
	python3 -m venv .venv
	$(PY) -m pip install -q -r requirements.txt

test:
	$(PY) tests/test_offline.py
	$(PY) tests/test_pairing.py
	@command -v node >/dev/null && node tests/test_page.js output/rover_lookup.html || \
		echo "(skipping the page test - node is not installed)"

# ~35 minutes and ~1,550 requests against a government service. Keep the
# throttling in rover/settings.py as it is.
crawl:
	$(PY) -m scrapy crawl rover -a list=sev -a details=1
	$(PY) -m scrapy crawl rover -a list=mre -a details=1

pair:
	$(PY) -m rover.pair

check:
	$(PY) scripts/check_fresh.py

page:
	$(PY) -m rover.page

# full refresh, in the same order CI uses
refresh: crawl pair check page
	@echo "built output/rover_lookup.html"

serve:
	@echo "http://127.0.0.1:8765/rover_lookup.html"
	@cd output && $(PY) -m http.server 8765 --bind 127.0.0.1

clean:
	rm -rf output/*.json output/rover_lookup.html site
