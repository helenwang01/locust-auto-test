PY ?= python3

.PHONY: help
help:
	@echo "Targets: deps, run-ws, run-tcp, run-speech"

.PHONY: deps
deps:
	$(PY) -m pip install -r requirements.txt

.PHONY: run-ws
run-ws:
	locust -f locustfile_msync.py --headless -u 100 -r 50 -t 5m --csv=out/ws --stop-timeout 30

.PHONY: run-tcp
run-tcp:
	locust -f locustfile_msync.py --headless -u 100 -r 50 -t 5m --csv=out/tcp --stop-timeout 30

.PHONY: run-speech
run-speech:
	bash scripts/run_speech_pressure.sh 20 5 5m
