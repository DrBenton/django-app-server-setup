
.PHONY: check-code-quality
check-code-quality:
# Bash-Fu is my greatest passion. (NO)
	@exit_codes=0 ; \
		${MAKE} black ; exit_codes=$$(( $$exit_codes + $$? )) ; \
		${MAKE} lint ; exit_codes=$$(( $$exit_codes + $$? )) ; \
		${MAKE} mypy ; exit_codes=$$(( $$exit_codes + $$? )) ; \
		exit $$exit_codes
 
.PHONY: black
black:
	@echo "Running Black..."
	@black setup.py
	@echo "Done.\n"

.PHONY: lint
lint:
	@echo "Running PyLint..."
	@pylint setup.py
	@echo "Done.\n"

.PHONY: mypy
mypy:
	@echo "Running MyPy..."
	@mypy setup.py
	@echo "Done.\n"
