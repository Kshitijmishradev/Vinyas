#!/bin/sh
set -eu

api_url="${VINYAS_SMOKE_API:-https://vinyas-api.onrender.com}"
repository_url="${VINYAS_SMOKE_REPOSITORY:-https://github.com/Kshitijmishradev/Vinyas}"

created="$(curl --fail --silent --show-error \
  --header 'Content-Type: application/json' \
  --data "{\"repository_url\":\"${repository_url}\"}" \
  "${api_url}/api/v1/analyses")"
analysis_id="$(printf '%s' "$created" | python -c 'import json,sys; print(json.load(sys.stdin)["id"])')"

attempt=0
while [ "$attempt" -lt 120 ]; do
  status_payload="$(curl --fail --silent --show-error "${api_url}/api/v1/analyses/${analysis_id}")"
  job_status="$(printf '%s' "$status_payload" | python -c 'import json,sys; print(json.load(sys.stdin)["status"])')"
  case "$job_status" in
    complete)
      curl --fail --silent --show-error "${api_url}/api/v1/analyses/${analysis_id}/graph" >/dev/null
      printf 'Public repository smoke test passed: %s\n' "$analysis_id"
      exit 0
      ;;
    failed|cancelled)
      printf '%s\n' "$status_payload" >&2
      exit 1
      ;;
  esac
  attempt=$((attempt + 1))
  sleep 1
done

printf 'Public repository smoke test timed out: %s\n' "$analysis_id" >&2
exit 1
