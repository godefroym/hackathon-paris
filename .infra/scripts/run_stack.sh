#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

SERVICES=(
  temporal
  temporal-create-namespace
  temporal-ui
  app-web
  app-queue
  app-reverb
  workflows-worker
)

usage() {
  cat <<'EOF'
Usage:
  ./scripts/run_stack.sh up [--build]
  ./scripts/run_stack.sh down
  ./scripts/run_stack.sh restart [--build]
  ./scripts/run_stack.sh ps
  ./scripts/run_stack.sh logs [service]

Commands:
  up       Start the full stack needed for realtime fact-checking.
  down     Stop and remove stack containers.
  restart  Equivalent to down + up.
  ps       Show stack services status.
  logs     Follow logs for a service (default: workflows-worker).
EOF
}

require_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "Error: docker command not found. Install Docker Desktop first." >&2
    exit 1
  fi
  if ! docker compose version >/dev/null 2>&1; then
    echo "Error: docker compose plugin not available." >&2
    exit 1
  fi
}

ensure_env_file() {
  local env_file="${REPO_ROOT}/cle.env"
  local example_file="${REPO_ROOT}/cle.env.example"
  if [[ -f "${env_file}" ]]; then
    return
  fi
  if [[ -f "${example_file}" ]]; then
    cp "${example_file}" "${env_file}"
    echo "Created ${env_file} from cle.env.example"
    echo "Set MISTRAL_API_KEY in ${env_file} before running production tests."
  else
    echo "Warning: ${env_file} missing and cle.env.example not found." >&2
  fi
}

compose() {
  (cd "${REPO_ROOT}" && docker compose "$@")
}

cmd_up() {
  local extra_args=()
  if [[ "${1:-}" == "--build" ]]; then
    extra_args+=("--build")
  elif [[ -n "${1:-}" ]]; then
    echo "Unknown option for up: ${1}" >&2
    usage
    exit 1
  fi

  ensure_env_file
  compose up -d "${extra_args[@]}" "${SERVICES[@]}"
  compose ps
}

cmd_down() {
  compose down
}

cmd_restart() {
  local opt="${1:-}"
  cmd_down
  if [[ -n "${opt}" ]]; then
    cmd_up "${opt}"
  else
    cmd_up
  fi
}

cmd_ps() {
  compose ps
}

cmd_logs() {
  local service="${1:-workflows-worker}"
  compose logs -f "${service}"
}

main() {
  require_docker
  local command="${1:-}"
  case "${command}" in
    up)
      cmd_up "${2:-}"
      ;;
    down)
      cmd_down
      ;;
    restart)
      cmd_restart "${2:-}"
      ;;
    ps)
      cmd_ps
      ;;
    logs)
      cmd_logs "${2:-}"
      ;;
    -h|--help|help|"")
      usage
      ;;
    *)
      echo "Unknown command: ${command}" >&2
      usage
      exit 1
      ;;
  esac
}

main "$@"
