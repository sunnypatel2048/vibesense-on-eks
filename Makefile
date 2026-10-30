# Lock files: fully pinned dependency trees generated from requirements/*.in.
# dev.txt is cross-platform (your Mac and CI); app.txt and ai.txt are resolved for
# the images: Linux arm64, Python 3.12. Constrained by dev.txt so shared packages
# get the same versions everywhere.
LOCK = uv pip compile --quiet --python-version 3.12 $(LOCK_ARGS)
# PyTorch's CPU-only index, for torch==...+cpu (see requirements/ai.in). That index
# also mirrors old copies of common packages (urllib3, setuptools, ...), so uv
# must pick the best version across both indexes, not the first index that has a
# package. Both indexes are first-party; see docs/security.md.
TORCH_CPU = --extra-index-url https://download.pytorch.org/whl/cpu --emit-index-url --index-strategy unsafe-best-match
# Extra flags for one run, e.g. make lock LOCK_ARGS="--upgrade-package torch"
LOCK_ARGS ?=
IMAGE_PLATFORM = --python-platform aarch64-unknown-linux-gnu

.PHONY: lock test

lock:
	$(LOCK) $(TORCH_CPU) --universal requirements/dev.in -o requirements/dev.txt
	$(LOCK) --index-strategy unsafe-best-match $(IMAGE_PLATFORM) -c requirements/dev.txt requirements/app.in -o requirements/app.txt
	$(LOCK) $(TORCH_CPU) $(IMAGE_PLATFORM) -c requirements/dev.txt requirements/ai.in -o requirements/ai.txt

test:
	python -m pytest -q
