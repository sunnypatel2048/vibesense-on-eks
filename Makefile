# Lock files: fully pinned dependency trees generated from requirements/*.in.
# dev.txt is cross-platform (your Mac and CI); app.txt and ai.txt are resolved for
# the images: Linux arm64, Python 3.12. Constrained by dev.txt so shared packages
# get the same versions everywhere.
LOCK = uv pip compile --quiet --python-version 3.12
IMAGE_PLATFORM = --python-platform aarch64-unknown-linux-gnu

.PHONY: lock test

lock:
	$(LOCK) --universal requirements/dev.in -o requirements/dev.txt
	$(LOCK) $(IMAGE_PLATFORM) -c requirements/dev.txt requirements/app.in -o requirements/app.txt
	$(LOCK) $(IMAGE_PLATFORM) -c requirements/dev.txt requirements/ai.in -o requirements/ai.txt

test:
	python -m pytest -q
