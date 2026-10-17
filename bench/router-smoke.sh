#!/bin/sh
# Smoke-test root's runtime against the local AgentRouter proxy from inside a
# container: does the wire protocol, streaming and tool calling work?
set -eu
cd "$(dirname "$0")/.."

KEY=$(python3 -c "import json;print(json.load(open('$HOME/.root-agentrouter/settings.json'))['openrouter_api_key'])")
BIN="$PWD/runtime/target-linux/release/kimi-agent"
[ -f "$BIN" ] || { echo "run bench/build-linux.sh first" >&2; exit 1; }

docker rm -f root-smoke >/dev/null 2>&1 || true
docker run -d --name root-smoke --add-host=host.docker.internal:host-gateway \
  -e AR_KEY="$KEY" alpine:3.20 sleep 900 >/dev/null
docker cp "$BIN" root-smoke:/opt/kimi-agent >/dev/null
docker cp agent root-smoke:/opt/agent >/dev/null
docker exec root-smoke chmod 755 /opt/kimi-agent

docker exec -e AR_KEY="$KEY" root-smoke sh -c '
cat > /tmp/config.json <<EOF
{"default_model":"main","default_thinking":false,
 "loop_control":{"max_steps_per_turn":12,"max_retries_per_step":2,"max_ralph_iterations":0,"reserved_context_size":50000},
 "providers":{"openrouter":{"type":"kimi","base_url":"http://host.docker.internal:8319/v1","api_key":"$AR_KEY","prompt_cache":false}},
 "models":{"main":{"provider":"openrouter","model":"deepseek-v4-flash","max_context_size":200000,"capabilities":[]}}}
EOF
chmod 600 /tmp/config.json
(echo "{\"jsonrpc\":\"2.0\",\"method\":\"prompt\",\"id\":\"1\",\"params\":{\"user_input\":\"Run the shell command: echo router-ok. Then reply with exactly: done\"}}"; sleep 120) \
 | /opt/kimi-agent --config-file /tmp/config.json --agent-file /opt/agent/agent.yaml --yolo 2>/tmp/err.log \
 | (while IFS= read -r line; do echo "$line"; case "$line" in *\"id\":\"1\"*) break ;; esac; done; kill 0 2>/dev/null) > /tmp/out.txt || true
grep -o "\"type\":\"[A-Za-z]*\"" /tmp/out.txt | sort | uniq -c
echo "--- tool calls ---"
grep -o "\"name\":\"[A-Za-z]*\"" /tmp/out.txt | sort | uniq -c
echo "--- result ---"
tail -c 600 /tmp/out.txt
echo
echo "--- stderr ---"
tail -c 600 /tmp/err.log
'
