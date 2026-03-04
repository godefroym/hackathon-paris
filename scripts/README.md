# Scripts

This directory contains utility scripts for environment setup, database initialization, and system validation.

## Key Scripts
- `setup-*.sh`: Bash scripts to initialize different database backends (MySQL, Postgres, Cassandra).
- `run_stack.sh`: Main script to start/stop the Docker Compose stack.
- `validate-temporal.sh`: Checks if the Temporal server is healthy and the namespace is created.
- `mock_fact_check_receiver.py`: A simple Python server to test POST results without the full OBS controller.
